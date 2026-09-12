"""
core.py — Shared constants, journal profile loader, and report builder.
"""

import hashlib
import json
import logging
import shutil
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

__version__ = "2.1.1"

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
        logger.warning("Could not load journal profile %s: %s", profile_path, e)
        return ""

# ---------------------------------------------------------------------------
# Agent checkpoints  (crash recovery for long-running reviews)
# ---------------------------------------------------------------------------

_CHECKPOINT_DIRNAME = ".reviewpanel_checkpoints"


def _checkpoint_dir(manuscript_data: dict) -> Path:
    """Hidden per-manuscript checkpoint folder next to the manuscript."""
    source = Path(manuscript_data["source_path"])
    return source.parent / _CHECKPOINT_DIRNAME / source.stem


def manuscript_hash(manuscript_data: dict) -> str:
    """SHA-256 of the manuscript full text (checkpoint validity key)."""
    text = manuscript_data["full_text"]
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def save_checkpoint(
    manuscript_data: dict, model: str, agent_num: int, output: str
) -> None:
    """
    Persist one agent's output to disk. Best-effort: any failure is logged
    and swallowed so checkpointing can never abort a running review.
    """
    try:
        ckpt_dir = _checkpoint_dir(manuscript_data)
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        meta_path = ckpt_dir / "meta.json"
        meta = {
            "manuscript_sha256": manuscript_hash(manuscript_data),
            "model": model,
            "version": __version__,
        }
        stale = True
        if meta_path.exists():
            try:
                old = json.loads(
                    meta_path.read_text(encoding="utf-8", errors="replace")
                )
                stale = (
                    old.get("manuscript_sha256") != meta["manuscript_sha256"]
                    or old.get("model") != meta["model"]
                )
            except Exception:
                stale = True
        if stale:
            # Manuscript edited or model changed: drop the previous run's
            # agent files so a later resume can never mix two runs' outputs.
            for old_file in ckpt_dir.glob("agent_*.md"):
                old_file.unlink(missing_ok=True)
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        path = ckpt_dir / f"agent_{agent_num}.md"
        path.write_text(output, encoding="utf-8")
    except Exception as e:
        logger.warning("Could not save checkpoint for agent %d: %s", agent_num, e)


def load_checkpoints(manuscript_data: dict, model: str) -> dict[int, str]:
    """
    Return {agent_num: output} for completed checkpoints matching this
    manuscript (by content hash) and model. Returns {} when nothing valid
    exists; a stale hash or different model silently invalidates them.
    """
    try:
        ckpt_dir = _checkpoint_dir(manuscript_data)
        meta_path = ckpt_dir / "meta.json"
        if not meta_path.exists():
            return {}
        meta = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
        if meta.get("manuscript_sha256") != manuscript_hash(manuscript_data):
            return {}
        if meta.get("model") != model:
            return {}
        found: dict[int, str] = {}
        for n in range(1, 7):
            path = ckpt_dir / f"agent_{n}.md"
            if path.exists():
                found[n] = path.read_text(encoding="utf-8", errors="replace")
        return found
    except Exception as e:
        logger.warning("Could not read checkpoints: %s", e)
        return {}


def clear_checkpoints(manuscript_data: dict) -> None:
    """Delete this manuscript's checkpoint folder (best-effort)."""
    try:
        ckpt_dir = _checkpoint_dir(manuscript_data)
        if ckpt_dir.exists():
            shutil.rmtree(ckpt_dir)
        base = ckpt_dir.parent
        if base.exists() and not any(base.iterdir()):
            base.rmdir()
    except Exception as e:
        logger.warning("Could not clear checkpoints: %s", e)

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

# Expected section markers per agent — mirrors the "Output:" specs in the
# agents.py prompts. Case-insensitive substring match; a light sanity check.
_EXPECTED_MARKERS = {
    1: ["Critical Issues", "Minor Issues", "Style Patterns"],
    2: ["Critical Inconsistencies", "Sample Flow Errors", "Terminology Drift"],
    3: ["Causal Overclaiming", "Clinical/Statistical Conflation",
        "Missing Caveats"],
    4: ["Methodological Errors", "Incomplete Statistical Reporting",
        "Regression Issues"],
    5: ["Missing Elements in Tables/Figures", "Formatting Inconsistencies"],
    6: [f"Part {n}" for n in range(1, 8)],
}


def _missing_markers(agent_num: int, output: str) -> list[str]:
    """Return the expected section markers absent from an agent's output."""
    lowered = output.lower()
    return [
        m for m in _EXPECTED_MARKERS.get(agent_num, [])
        if m.lower() not in lowered
    ]


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
        "> *See Agent 6 — Part 7: Priority Action Items for the consolidated triage.*",
        "",
        "---",
        "",
    ]

    for i, output in enumerate(agent_outputs, start=1):
        lines += [
            f"## {_SECTION_HEADERS[i]}",
            "",
        ]
        missing = _missing_markers(i, output)
        if missing:
            logger.warning(
                "Agent %d output is missing expected section(s): %s",
                i, ", ".join(missing),
            )
            lines += [
                "> ⚠ This section may be incomplete — the model did not "
                "return the expected structure "
                f"(missing: {', '.join(missing)}).",
                "",
            ]
        lines += [
            output.strip(),
            "",
            "---",
            "",
        ]


    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
