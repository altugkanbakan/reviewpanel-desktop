"""
Tests for the bundled knowledge base (agents.load_knowledge_base /
verify_knowledge_base) against the REAL files in src/knowledge_base.

Guards:
  * All 5 KB keys load with non-empty content — the sentinel for the
    src/ move: if KB_BASE resolution breaks, load_knowledge_base()
    silently falls back to empty strings and reviews become worthless.
  * verify_knowledge_base returns [] on an intact install and reports
    the damaged keys on a broken one.
  * core.kb_content_hash is key-order independent (cache-key component).
"""

import agents
import core
from agents import load_knowledge_base, verify_knowledge_base

EXPECTED_KEYS = {"ama_style", "patient_first", "strobe", "consort", "sampl"}


class TestLoadKnowledgeBase:
    def test_all_five_keys_present_and_non_empty(self):
        kb = load_knowledge_base()
        assert set(kb) == EXPECTED_KEYS
        for key, content in kb.items():
            assert content.strip(), (
                f"KB entry '{key}' is empty — KB_BASE path resolution is "
                f"probably broken (KB_BASE={core.KB_BASE})"
            )

    def test_substantial_content(self):
        """Guard against truncated placeholder files sneaking in."""
        kb = load_knowledge_base()
        for key, content in kb.items():
            assert len(content) > 200, f"KB entry '{key}' suspiciously small"


class TestVerifyKnowledgeBase:
    def test_intact_install_reports_nothing(self):
        assert verify_knowledge_base() == []

    def test_broken_install_reports_missing_keys(self, tmp_path, monkeypatch):
        good = tmp_path / "good.md"
        good.write_text("real guideline content", encoding="utf-8")
        empty = tmp_path / "empty.md"
        empty.write_text("   \n", encoding="utf-8")
        broken_files = {
            "ama_style": good,
            "patient_first": tmp_path / "missing.csv",  # does not exist
            "strobe": empty,                            # exists but blank
            "consort": good,
            "sampl": tmp_path / "also_missing.md",
        }
        monkeypatch.setattr(agents, "_KB_FILES", broken_files)
        assert sorted(verify_knowledge_base()) == [
            "patient_first", "sampl", "strobe",
        ]

    def test_broken_install_still_loads_with_fallback(
        self, tmp_path, monkeypatch
    ):
        """load_knowledge_base never raises; damaged entries become ''."""
        monkeypatch.setattr(
            agents, "_KB_FILES",
            {"ama_style": tmp_path / "gone.md"},
        )
        kb = load_knowledge_base()
        assert kb == {"ama_style": ""}


class TestKbContentHash:
    def test_order_independent_on_real_kb(self):
        kb = load_knowledge_base()
        shuffled = dict(reversed(list(kb.items())))
        assert core.kb_content_hash(shuffled) == core.kb_content_hash(kb)
