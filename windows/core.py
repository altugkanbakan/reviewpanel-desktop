"""
core.py — Shared constants, journal profile loader, and report builder.
"""

import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Journal registry
# ---------------------------------------------------------------------------

JOURNAL_FILES = {
    "JAMA": "JAMA.json",
    "CJEM": "CJEM.json",
    "AnnalsEM": "Annals_of_EM.json",
    "Resuscitation": "Resuscitation.json",
}

KNOWN_JOURNALS = ["top-medical"] + list(JOURNAL_FILES.keys()) + [
    "NEJM", "Lancet", "BMJ", "AJEM", "JAMIA", "BMCMedEd", "SimHealthcare",
]

KB_BASE = Path(__file__).parent / "knowledge_base"

# ---------------------------------------------------------------------------
# Journal profile loader
# ---------------------------------------------------------------------------

def load_journal_profile(journal: str, kb_base: Path = KB_BASE) -> str:
    if journal == "top-medical" or journal not in JOURNAL_FILES:
        return ""
    profile_path = kb_base / "journal_profiles" / JOURNAL_FILES[journal]
    try:
        return profile_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"[WARNING] Could not load journal profile {profile_path}: {e}", file=sys.stderr)
        return ""

# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

_SECTION_HEADERS = {
    1: "1. Medical Style, Grammar & Reporting Guidelines",
    2: "2. Internal Consistency & PICO Verification",
    3: "3. Clinical Claims, Causality & Confounding",
    4: "4. Biostatistics, Methodology & Notation",
    5: "5. Tables, Figures & Clinical Documentation",
    6: "6. Clinical Impact & Adversarial Referee",
}


def build_report(
    agent_outputs: list[str],
    manuscript_data: dict,
    journal: str,
    model: str,
    output_dir: Path | None = None,
) -> Path:
    """
    Assemble all 6 agent outputs into a single Markdown report.
    Saves to output_dir (defaults to CWD) as PRE_SUBMISSION_MEDICAL_REVIEW_YYYY-MM-DD.md.
    Returns the saved Path.
    """
    today = date.today().isoformat()
    filename = f"PRE_SUBMISSION_MEDICAL_REVIEW_{today}.md"
    output_path = (output_dir or Path.cwd()) / filename

    lines: list[str] = []

    lines += [
        "# Medical Pre-Submission Referee Report",
        "",
        f"**Date:** {today}",
        f"**Target Journal:** {journal}",
        f"**Manuscript:** {manuscript_data['title']}",
        f"**Source:** {manuscript_data['source_path']}",
        f"**Model:** {model}",
        "",
        "---",
        "",
        "## Overall Assessment",
        "",
        "> *See Priority Action Items section at the end for the consolidated triage.*",
        "",
        "---",
        "",
    ]

    for i, output in enumerate(agent_outputs, start=1):
        lines += [
            f"## {_SECTION_HEADERS[i]}",
            "",
            output.strip(),
            "",
            "---",
            "",
        ]

    lines += [
        "## Priority Action Items",
        "",
        "*(Synthesised from all 6 agent reviews above)*",
        "",
        "### Critical",
        "",
        "<!-- Reviewer: list critical items here -->",
        "",
        "### Major",
        "",
        "<!-- Reviewer: list major items here -->",
        "",
        "### Minor",
        "",
        "<!-- Reviewer: list minor items here -->",
        "",
    ]

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
