"""
Tests for context-window planning and the Agent 6 prompt diet (agents.py).

Guards:
  * plan_context: 4096 floor, ceil-to-2048-step, 32768 ceiling.
  * trim_previous_outputs: respects the budget, never deletes an output
    wholesale, drops low-priority sections (Style Patterns, Minor Issues)
    before critical ones, marks the cut.
  * prepare_agent6_prompt: no trim when everything fits tier A; when it
    does not fit, trims and tries to stay in the same window (no model
    reload / prefix-cache loss).
"""

import agents
from agents import (
    _TRIM_NOTICE,
    _estimate_tokens,
    plan_context,
    prepare_agent6_prompt,
    trim_previous_outputs,
)


class TestPlanContext:
    def test_floor_is_4096(self):
        assert plan_context(0) == 4096
        assert plan_context(1) == 4096
        # reserve (2048) + prompt exactly fills the floor
        assert plan_context(2048) == 4096

    def test_rounds_up_to_2048_multiple(self):
        # needed = 2049 + 2048 = 4097 -> next step multiple = 6144
        assert plan_context(2049) == 6144
        # needed = 10000 + 2048 = 12048 -> 12288
        assert plan_context(10000) == 12288
        # exact multiple: needed = 6144 + 2048 = 8192 stays 8192
        assert plan_context(6144) == 8192

    def test_ceiling_is_32768(self):
        assert plan_context(1_000_000) == 32768
        # boundary: exactly at the ceiling
        assert plan_context(32768 - 2048) == 32768
        # one past the ceiling still clamps
        assert plan_context(32768 - 2048 + 1) == 32768

    def test_custom_reserve(self):
        # needed = 100 + 0 = 100 -> floor
        assert plan_context(100, reserve=0) == 4096
        # needed = 8000 + 0 = 8000 -> 8192
        assert plan_context(8000, reserve=0) == 8192


def _sentences(n: int, tag: str) -> str:
    return " ".join(f"{tag} finding {i} with enough words to count." for i in range(n))


def _structured_output() -> str:
    """Agent-1-style output with critical + low-priority sections."""
    return "\n".join([
        "**Critical Issues**",
        _sentences(20, "critical"),
        "",
        "**Minor Issues**",
        _sentences(20, "minor"),
        "",
        "**Style Patterns**",
        _sentences(20, "style"),
    ])


class TestTrimPreviousOutputs:
    def test_under_budget_untouched(self):
        outputs = ["short output one", "short output two"]
        assert trim_previous_outputs(outputs, 10_000) == outputs

    def test_respects_budget(self):
        outputs = ["word " * 4000 for _ in range(5)]  # ~5000 tok each
        budget = 3000
        trimmed = trim_previous_outputs(outputs, budget)
        assert sum(_estimate_tokens(t) for t in trimmed) <= budget

    def test_no_output_deleted_entirely(self):
        outputs = ["word " * 4000 for _ in range(5)]
        trimmed = trim_previous_outputs(outputs, 100)  # absurdly small
        assert len(trimmed) == 5
        for t in trimmed:
            assert t.strip()  # every agent keeps something

    def test_trim_notice_marks_the_cut(self):
        outputs = ["word " * 4000]
        (trimmed,) = trim_previous_outputs(outputs, 500)
        assert _TRIM_NOTICE.strip() in trimmed

    def test_low_priority_sections_drop_first(self):
        text = _structured_output()
        total = _estimate_tokens(text)
        # Budget forcing a cut, but roomy enough that dropping only the
        # lowest-priority section (Style Patterns) suffices.
        style_tokens = _estimate_tokens(
            "**Style Patterns**\n" + _sentences(20, "style")
        )
        budget = total - style_tokens + 30
        assert budget < total
        (trimmed,) = trim_previous_outputs([text], budget)
        assert "Critical Issues" in trimmed
        assert "Minor Issues" in trimmed
        assert "Style Patterns" not in trimmed

    def test_critical_survives_when_both_low_priority_drop(self):
        text = _structured_output()
        critical_tokens = _estimate_tokens(
            "**Critical Issues**\n" + _sentences(20, "critical")
        )
        budget = critical_tokens + 40
        (trimmed,) = trim_previous_outputs([text], budget)
        assert "Critical Issues" in trimmed
        assert "Style Patterns" not in trimmed
        assert "Minor Issues" not in trimmed


class TestPrepareAgent6Prompt:
    MANUSCRIPT = "Short manuscript body for tier tests."

    def test_fits_tier_a_untrimmed(self, kb):
        outputs = [f"tiny output {n}" for n in range(5)]
        prompt, num_ctx, info = prepare_agent6_prompt(
            self.MANUSCRIPT, kb, "", outputs, tier_a_ctx=32768,
        )
        assert info["trimmed"] is False
        assert num_ctx == 32768
        # untrimmed == the straightforward full prompt
        assert prompt == agents.build_prompt(
            6, self.MANUSCRIPT, kb, "", outputs
        )
        for out in outputs:
            assert out in prompt

    def test_overflow_trims_and_stays_in_window(self, kb):
        outputs = ["word " * 8000 for _ in range(5)]  # ~10k tok total
        tier_a = 4096
        prompt, num_ctx, info = prepare_agent6_prompt(
            self.MANUSCRIPT, kb, "", outputs, tier_a_ctx=tier_a,
        )
        assert info["trimmed"] is True
        assert info["after_tokens"] < info["before_tokens"]
        # Stays in the tier-A window: no model reload
        assert num_ctx == tier_a
        # And the trimmed prompt actually fits that window
        assert _estimate_tokens(prompt) + 2048 <= num_ctx
        # Every agent's material is still represented (headings present)
        assert prompt.count("### Agent") == 5

    def test_reported_num_ctx_matches_return(self, kb):
        outputs = ["word " * 8000 for _ in range(5)]
        _, num_ctx, info = prepare_agent6_prompt(
            self.MANUSCRIPT, kb, "", outputs, tier_a_ctx=4096,
        )
        assert info["num_ctx"] == num_ctx
