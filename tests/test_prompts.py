"""
Regression tests for the prompt builders (agents.py).

Guards:
  * Agent 6 embeds previous_outputs when given — and only then. (The
    original faz0 bug: the GUI never passed the outputs, so Agent 6
    synthesised from nothing.)
  * The manuscript block is byte-identical and FIRST across all 6 agents
    (Ollama prefix KV-cache reuse silently dies if this drifts).
  * PROMPT_VERSION exists and is an int (cache-key component).
"""

import agents
from agents import PROMPT_VERSION, build_prompt

MANUSCRIPT = "Title line.\n\nWe measured X in Y patients and found Z."

PREVIOUS = [f"Findings of agent {n}: issue A, issue B." for n in range(1, 6)]


class TestAgent6PreviousOutputs:
    def test_previous_outputs_are_embedded(self, kb):
        prompt = build_prompt(6, MANUSCRIPT, kb, "", PREVIOUS)
        assert "## Previous Agent Outputs" in prompt
        for out in PREVIOUS:
            assert out in prompt

    def test_no_previous_outputs_no_block(self, kb):
        prompt = build_prompt(6, MANUSCRIPT, kb, "", None)
        assert "## Previous Agent Outputs" not in prompt
        for out in PREVIOUS:
            assert out not in prompt

    def test_journal_profile_embedded_when_given(self, kb):
        profile = "Desk-reject triggers: no CONSORT diagram."
        with_profile = build_prompt(6, MANUSCRIPT, kb, profile, PREVIOUS)
        without = build_prompt(6, MANUSCRIPT, kb, "", PREVIOUS)
        assert "## Target Journal Profile" in with_profile
        assert profile in with_profile
        assert "## Target Journal Profile" not in without


class TestPrefixInvariant:
    """The manuscript block must open every prompt, byte-identical."""

    def test_manuscript_block_is_common_prefix(self, kb):
        expected_prefix = "## Manuscript\n\n" + MANUSCRIPT + "\n\n---\n\n"
        for agent_num in range(1, 7):
            prompt = build_prompt(
                agent_num, MANUSCRIPT, kb,
                journal_profile_text="profile" if agent_num == 6 else "",
                previous_outputs=PREVIOUS if agent_num == 6 else None,
            )
            assert prompt.startswith(expected_prefix), (
                f"Agent {agent_num} prompt does not start with the shared "
                "manuscript block — prefix KV cache reuse is broken"
            )

    def test_no_agent_specific_content_before_manuscript(self, kb):
        """Nothing variable (agent number, role) may precede the block."""
        prompts = [
            build_prompt(n, MANUSCRIPT, kb, "", None) for n in range(1, 7)
        ]
        block_len = len("## Manuscript\n\n" + MANUSCRIPT)
        first_blocks = {p[:block_len] for p in prompts}
        assert len(first_blocks) == 1

    def test_role_and_task_come_after_manuscript(self, kb):
        prompt = build_prompt(1, MANUSCRIPT, kb)
        assert prompt.index("## Manuscript") < prompt.index("## Your Task")
        assert prompt.index(MANUSCRIPT) < prompt.index("You are acting as a")


class TestPromptVersion:
    def test_exists_and_is_int(self):
        assert hasattr(agents, "PROMPT_VERSION")
        assert type(PROMPT_VERSION) is int
