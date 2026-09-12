"""
Tests for the report builder (core.build_report).

Guards:
  * All 6 section headers are written.
  * A malformed agent output gets a "may be incomplete" warning but the
    report is STILL produced (never refuse a review that already ran).
  * The Run Statistics block appears only when run_stats is passed
    (backwards compatibility with older call sites).
"""

import core
from core import build_report


def _compliant_outputs():
    """Six outputs that contain every expected section marker."""
    outs = []
    for n in range(1, 6):
        markers = core._EXPECTED_MARKERS[n]
        outs.append(
            "\n\n".join(f"**{m}**\n1. finding" for m in markers)
        )
    outs.append(
        "\n\n".join(f"**Part {i}** content" for i in range(1, 8))
    )
    return outs


class TestBuildReport:
    def test_all_six_section_headers_present(self, tmp_path, manuscript_data):
        path = build_report(
            _compliant_outputs(), manuscript_data, "JAMA", "qwen2.5:7b",
            output_dir=tmp_path,
        )
        text = path.read_text(encoding="utf-8")
        for header in core._SECTION_HEADERS.values():
            assert f"## {header}" in text
        assert "may be incomplete" not in text

    def test_report_written_to_output_dir(self, tmp_path, manuscript_data):
        path = build_report(
            _compliant_outputs(), manuscript_data, "JAMA", "qwen2.5:7b",
            output_dir=tmp_path,
        )
        assert path.parent == tmp_path
        assert path.name.startswith("PRE_SUBMISSION_MEDICAL_REVIEW_")
        assert path.suffix == ".md"

    def test_metadata_lines_present(self, tmp_path, manuscript_data):
        path = build_report(
            _compliant_outputs(), manuscript_data, "CJEM", "llama3:8b",
            output_dir=tmp_path,
        )
        text = path.read_text(encoding="utf-8")
        assert "**Target Journal:** CJEM" in text
        assert "**Model:** llama3:8b" in text
        assert manuscript_data["title"] in text


class TestIncompleteOutputs:
    def test_warns_but_still_produces_report(self, tmp_path, manuscript_data):
        outputs = _compliant_outputs()
        outputs[0] = "Free-form rambling without the expected structure."
        path = build_report(
            outputs, manuscript_data, "JAMA", "qwen2.5:7b",
            output_dir=tmp_path,
        )
        assert path.exists()  # never refuses
        text = path.read_text(encoding="utf-8")
        assert "may be incomplete" in text
        # the malformed output itself is still included
        assert "Free-form rambling" in text
        # names the missing sections
        assert "Critical Issues" in text

    def test_partial_markers_lists_only_missing(self, tmp_path, manuscript_data):
        outputs = _compliant_outputs()
        outputs[1] = "**Critical Inconsistencies**\n1. x"  # 2 of 3 missing
        path = build_report(
            outputs, manuscript_data, "JAMA", "qwen2.5:7b",
            output_dir=tmp_path,
        )
        text = path.read_text(encoding="utf-8")
        assert "may be incomplete" in text
        assert "Sample Flow Errors" in text
        assert "Terminology Drift" in text


class TestRunStats:
    STATS = {
        "total_seconds": 125.0,
        "agents": [
            {"agent": 1, "seconds": 30.0, "prompt_eval_count": 1000,
             "eval_count": 500, "eval_duration": 10_000_000_000},
            {"agent": 2, "restored": True},
        ],
    }

    def test_block_present_when_given(self, tmp_path, manuscript_data):
        path = build_report(
            _compliant_outputs(), manuscript_data, "JAMA", "qwen2.5:7b",
            output_dir=tmp_path, run_stats=self.STATS,
        )
        text = path.read_text(encoding="utf-8")
        assert "## Run Statistics" in text
        assert "**Total time:** 2m 5s" in text
        assert "(cache)" in text  # restored agent rendered as cache hit

    def test_block_absent_when_omitted(self, tmp_path, manuscript_data):
        path = build_report(
            _compliant_outputs(), manuscript_data, "JAMA", "qwen2.5:7b",
            output_dir=tmp_path,
        )
        assert "## Run Statistics" not in path.read_text(encoding="utf-8")

    def test_empty_stats_dict_treated_as_absent(self, tmp_path, manuscript_data):
        path = build_report(
            _compliant_outputs(), manuscript_data, "JAMA", "qwen2.5:7b",
            output_dir=tmp_path, run_stats={},
        )
        assert "## Run Statistics" not in path.read_text(encoding="utf-8")
