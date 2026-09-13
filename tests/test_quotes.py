"""
Tests for quote verification (core.quote_index / extract_claimed_quotes /
find_unverified_quotes) and its integration into core.build_report.

Guards:
  * Verbatim quotes verify — including with typographic quotes/dashes and
    different whitespace/line wrapping (must never false-alarm on those).
  * Suggested rewrites and quoted rules are model-authored text: they are
    never treated as claimed manuscript quotations.
  * Short quoted spans (< 8 words) are never judged.
  * Only long quotes with no 5-word overlap at all are flagged.
  * A flagged quote adds a warning note but the report stays COMPLETE
    (never refuse a review that already ran — same philosophy as the
    missing-marker check).

Thresholds were calibrated against real qwen2.5/qwen3 outputs; the fixture
manuscript below mirrors the structures those models produced.
"""

import core
from core import (
    build_report,
    extract_claimed_quotes,
    find_unverified_quotes,
    quote_index,
)
from test_report import _compliant_outputs

MANUSCRIPT = (
    "# Glycaemic Control Study\n"
    "\n"
    "We reviewed 840 subjects presenting to a single urban emergency\n"
    "department between January 2023 and December 2024. Elevated HbA1c\n"
    "proved to be the driver of readmission risk. Diabetics who are\n"
    "non-compliant represent the highest-risk group in this cohort."
)

FABRICATED = (
    "The intervention reduced mortality by nearly half across all "
    "prespecified subgroups at ninety days."
)


def _flag(output: str, full_text: str = MANUSCRIPT) -> list[str]:
    return find_unverified_quotes(output, quote_index(full_text))


class TestVerification:
    def test_verbatim_quote_verifies(self):
        out = ('*Quote:* "Elevated HbA1c proved to be the driver of '
               'readmission risk."')
        assert _flag(out) == []

    def test_typographic_quotes_and_dashes_verify(self):
        # Curly quotes around the span, an en dash the ASCII manuscript
        # does not even contain — models emit both. Must not false-alarm.
        out = ("*Quote:* “We reviewed 840 subjects presenting to a single "
               "urban emergency department between January 2023 – and "
               "December 2024.”")
        assert _flag(out) == []

    def test_whitespace_and_line_wrap_differences_verify(self):
        # Manuscript wraps mid-sentence; the model quotes it on one line.
        out = ('"We reviewed 840 subjects presenting to a single urban '
               'emergency department between January 2023 and December '
               '2024."')
        assert _flag(out) == []

    def test_fabricated_long_quote_is_flagged(self):
        assert _flag(f'*Quote:* "{FABRICATED}"') == [FABRICATED]

    def test_flagged_quotes_are_deduplicated(self):
        out = f'*Quote:* "{FABRICATED}"\n*Quote:* "{FABRICATED}"'
        assert _flag(out) == [FABRICATED]

    def test_partial_overlap_is_not_flagged(self):
        # Shortened/edited quote that still shares a 5-word run with the
        # manuscript — related to the text, so it must pass.
        out = ('"We reviewed 840 subjects presenting to a single urban ED '
               'between January 2023 and December 2024."')
        assert _flag(out) == []


class TestExtraction:
    def test_suggested_rewrite_is_not_a_claimed_quote(self):
        # Model-authored replacement text: not in the manuscript, but it
        # must NOT be flagged (this was the main false-alarm source in
        # the real qwen2.5:7b outputs).
        out = ('- *Suggested Replacement:* "Our study demonstrates the '
               'need for a re-examination of discharge practices for '
               'these patients."')
        assert extract_claimed_quotes(out) == []
        assert _flag(out) == []

    def test_should_be_corrected_to_is_not_a_claimed_quote(self):
        out = (f'- Example: "{FABRICATED}" should be corrected to '
               f'"{FABRICATED}"')
        # first span IS claimed (and fabricated), second is the rewrite
        assert extract_claimed_quotes(out) == [FABRICATED]

    def test_quoted_rule_is_not_a_claimed_quote(self):
        # qwen3 quotes knowledge-base rules back; never judge those.
        out = ('The rule states: "Do not use a leading zero before a '
               'decimal point if the number cannot exceed 1 there."')
        assert extract_claimed_quotes(out) == []

    def test_short_quote_is_never_judged(self):
        # "5 mm Hg" style fabrications are too short to call.
        assert extract_claimed_quotes('Example: "5 mm Hg"') == []
        assert _flag('Example: "p = .04" and "another short one"') == []

    def test_quote_never_crosses_lines(self):
        out = f'An unpaired " here\n*Quote:* "{FABRICATED}"'
        assert extract_claimed_quotes(out) == [FABRICATED]


class TestReportIntegration:
    def _manuscript_data(self):
        return {
            "title": "Glycaemic Control Study",
            "full_text": MANUSCRIPT,
            "figure_files": [],
            "table_files": [],
            "source_path": "C:/fake/manuscript.md",
        }

    def test_clean_outputs_get_no_quote_warning(self, tmp_path):
        path = build_report(
            _compliant_outputs(), self._manuscript_data(), "JAMA",
            "qwen2.5:7b", output_dir=tmp_path,
        )
        assert "could not be found in the manuscript" not in path.read_text(
            encoding="utf-8"
        )

    def test_flagged_quote_warns_but_report_stays_complete(self, tmp_path):
        outputs = _compliant_outputs()
        outputs[2] += f'\n\n*Quote:* "{FABRICATED}"'
        path = build_report(
            outputs, self._manuscript_data(), "JAMA", "qwen2.5:7b",
            output_dir=tmp_path,
        )
        text = path.read_text(encoding="utf-8")
        # warning present, count stated, example shown (shortened to 80)
        assert "1 quoted passage(s)" in text
        assert "could not be found in the manuscript" in text
        assert FABRICATED[:60] in text
        # report is still COMPLETE: every section, finding kept verbatim
        for header in core._SECTION_HEADERS.values():
            assert f"## {header}" in text
        assert FABRICATED in text.split("could not be found", 1)[1]

    def test_warning_shows_at_most_three_examples(self, tmp_path):
        fakes = [
            f"Entirely invented passage number {n} that never appears "
            "anywhere within the manuscript body." for n in range(1, 5)
        ]
        outputs = _compliant_outputs()
        outputs[0] += "".join(f'\n\n*Quote:* "{q}"' for q in fakes)
        text = build_report(
            outputs, self._manuscript_data(), "JAMA", "qwen2.5:7b",
            output_dir=tmp_path,
        ).read_text(encoding="utf-8")
        warning = next(
            line for line in text.splitlines() if "quoted passage(s)" in line
        )
        assert "4 quoted passage(s)" in warning
        assert "number 3" in warning
        assert "number 4" not in warning  # only 3 examples shown

    def test_missing_full_text_skips_check(self, tmp_path, manuscript_data):
        data = dict(manuscript_data, full_text="")
        outputs = _compliant_outputs()
        outputs[0] += f'\n\n*Quote:* "{FABRICATED}"'
        path = build_report(
            outputs, data, "JAMA", "qwen2.5:7b", output_dir=tmp_path,
        )
        assert "could not be found in the manuscript" not in path.read_text(
            encoding="utf-8"
        )


class TestCitationRequirement:
    """
    A span is judged only when its line claims it came from the manuscript.
    Calibrated against two real reports: the blocklist alone flagged a
    reviewer's own proposed sentences, because the giveaway word sat inside
    the quotation instead of before it.
    """

    SHORT_FABRICATION = "Alcoholics often face social stigma."

    def test_short_fabrication_with_citation_marker_is_flagged(self):
        # Five words. Real fabrications observed in a review of a study
        # about medical students were textbook sentences this short, and
        # an eight-word floor missed four of the seven.
        out = f'- **Sentence:** "{self.SHORT_FABRICATION}"'
        assert _flag(out) == [self.SHORT_FABRICATION]

    def test_fabrication_without_any_marker_is_not_judged(self):
        # No claim that this came from the manuscript, so no verdict.
        assert _flag(f'"{self.SHORT_FABRICATION}"') == []

    def test_reviewers_proposed_sentence_is_not_flagged(self):
        # Observed false alarm: the word that reveals this as a proposal
        # sits inside the quotation, where a prefix blocklist cannot see it.
        out = ('- Add a limitation statement: "A patient flow diagram is '
               'strongly recommended."')
        assert _flag(out) == []

    def test_citation_marker_does_not_rescue_a_real_quote(self):
        out = ('*Quote:* "Diabetics who are non-compliant represent the '
               'highest-risk group in this cohort."')
        assert _flag(out) == []
