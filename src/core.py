"""
core.py — Shared constants, journal profile loader, persistent
agent-output cache, and report builder.
"""

import hashlib
import json
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

from platforms import cache_dir

logger = logging.getLogger(__name__)

__version__ = "2.1.2"

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

# ---------------------------------------------------------------------------
# Resource resolution — single source of truth for bundled data paths.
# In a PyInstaller onefile build, data files are extracted to sys._MEIPASS;
# in a onedir build and in development, they sit next to this module.
# ---------------------------------------------------------------------------

def resource_path() -> Path:
    """Root folder that holds bundled resources (knowledge_base, ...)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).parent


KB_BASE = resource_path() / "knowledge_base"

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
# Persistent agent-output cache  (content-addressed, user-level)
#
# One mechanism serves both crash recovery ("resume this run") and reuse
# across runs: every finished agent output is stored on disk under a key
# derived from everything that determines that output. Same inputs -> same
# key -> hit; any change to the manuscript, model, knowledge base, prompt
# templates or (for Agent 6) the upstream material misses cleanly.
#
# Key schema — sha256 over newline-joined components (every component is a
# hex digest or a short token, so components cannot bleed into each other):
#
#   scheme tag
#   sha256(manuscript full_text)
#   agent_num
#   model
#   sha256(knowledge-base contents)
#   prompt_version     (agents.PROMPT_VERSION, bumped by hand)
#   aux                ("" for agents 1-5; for Agent 6 a digest over the
#                       journal profile + the five upstream outputs IN
#                       ORDER, because its prompt embeds them — a synthesis
#                       built from different upstream outputs or another
#                       target journal must never be reused)
#
# Layout: <cache_dir()>/<key>.md (the output) + <key>.json (metadata for
# diagnosis: agent, model, created, prompt_version, manuscript hash, title).
# ---------------------------------------------------------------------------

_CACHE_SCHEME = "reviewpanel-cache-v1"

# Eviction limits — the cache must not grow without bound. Entries older
# than _CACHE_MAX_AGE_DAYS go first, then the least-recently-used (cache
# hits touch mtime) until the total size is back under _CACHE_MAX_BYTES.
# 500 MB is on the order of ten thousand agent outputs (~10-50 KB each),
# far more than anyone revisits, and 60 days outlives a revision cycle.
_CACHE_MAX_BYTES = 500 * 1024 * 1024
_CACHE_MAX_AGE_DAYS = 60


def _cache_root() -> Path:
    """Cache root folder (single indirection point; tests may repoint it)."""
    return cache_dir()


def manuscript_hash(manuscript_data: dict) -> str:
    """SHA-256 of the manuscript full text (cache-key component)."""
    text = manuscript_data["full_text"]
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def kb_content_hash(kb: dict[str, str]) -> str:
    """
    SHA-256 over the loaded knowledge-base contents (key-order independent).
    Editing any KB file changes this and invalidates prior cached outputs.
    """
    h = hashlib.sha256()
    for key in sorted(kb):
        h.update(hashlib.sha256(key.encode("utf-8", errors="replace")).digest())
        h.update(
            hashlib.sha256(kb[key].encode("utf-8", errors="replace")).digest()
        )
    return h.hexdigest()


def cache_key(
    manuscript_data: dict,
    agent_num: int,
    model: str,
    kb: dict[str, str],
    prompt_version: int,
    journal_profile_text: str = "",
    previous_outputs: list[str] | None = None,
) -> str:
    """
    Content-addressed key for one agent's output (schema documented above).
    Agent 6 REQUIRES previous_outputs (agents 1-5, in order): its prompt
    embeds them, so leaving them out of the key would silently reuse a
    synthesis of different upstream outputs.
    """
    if agent_num == 6:
        if previous_outputs is None:
            raise ValueError(
                "cache_key: Agent 6 requires previous_outputs (agents 1-5)"
            )
        aux_h = hashlib.sha256()
        aux_h.update(
            hashlib.sha256(
                journal_profile_text.encode("utf-8", errors="replace")
            ).digest()
        )
        for out in previous_outputs:
            aux_h.update(
                hashlib.sha256(out.encode("utf-8", errors="replace")).digest()
            )
        aux = aux_h.hexdigest()
    else:
        aux = ""
    material = "\n".join([
        _CACHE_SCHEME,
        manuscript_hash(manuscript_data),
        str(agent_num),
        model,
        kb_content_hash(kb),
        str(prompt_version),
        aux,
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def cache_save(
    key: str,
    output: str,
    *,
    manuscript_data: dict,
    model: str,
    agent_num: int,
    prompt_version: int,
) -> None:
    """
    Persist one agent's output as <key>.md + <key>.json in the user-level
    cache. Best-effort: any failure is logged and swallowed so caching can
    never abort a running review.
    """
    try:
        root = _cache_root()
        root.mkdir(parents=True, exist_ok=True)
        meta = {
            "agent_num": agent_num,
            "model": model,
            "created": datetime.now().isoformat(timespec="seconds"),
            "prompt_version": prompt_version,
            "manuscript_sha256": manuscript_hash(manuscript_data),
            "title": str(manuscript_data.get("title", ""))[:120],
        }
        (root / f"{key}.md").write_text(output, encoding="utf-8")
        (root / f"{key}.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("Could not cache output of agent %d: %s", agent_num, e)


def cache_load(key: str) -> str | None:
    """
    Return the cached output for key, or None on a miss. Best-effort: any
    I/O error is a miss. A hit touches both files' mtime so eviction sees
    recently reused entries as fresh (LRU).
    """
    try:
        path = _cache_root() / f"{key}.md"
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        now = time.time()
        for p in (path, path.with_suffix(".json")):
            try:
                os.utime(p, (now, now))
            except OSError:
                pass
        return text
    except Exception as e:
        logger.warning("Cache read failed (%s…): %s", key[:12], e)
        return None


def load_cached_outputs(
    manuscript_data: dict,
    model: str,
    kb: dict[str, str],
    prompt_version: int,
    journal_profile_text: str = "",
) -> dict[int, str]:
    """
    Return {agent_num: output} for every agent whose output for these
    exact inputs is already cached. Agent 6 is looked up only when agents
    1-5 all hit, because its key depends on their outputs (in order).
    """
    found: dict[int, str] = {}
    try:
        for n in range(1, 6):
            out = cache_load(
                cache_key(manuscript_data, n, model, kb, prompt_version)
            )
            if out is not None:
                found[n] = out
        if len(found) == 5:
            out = cache_load(cache_key(
                manuscript_data, 6, model, kb, prompt_version,
                journal_profile_text, [found[n] for n in range(1, 6)],
            ))
            if out is not None:
                found[6] = out
    except Exception as e:
        logger.warning("Cache lookup failed: %s", e)
    return found


def cache_evict(
    max_bytes: int = _CACHE_MAX_BYTES,
    max_age_days: int = _CACHE_MAX_AGE_DAYS,
) -> int:
    """
    Bound the cache: delete entries older than max_age_days, then the
    least-recently-used (by mtime; hits refresh it) until the total size
    is under max_bytes. Returns the number of entries removed. Best-effort
    — callers run it at most once per review, off the main thread, and a
    failure must never stop the review.
    """
    removed = 0
    try:
        root = _cache_root()
        if not root.exists():
            return 0
        entries: list[tuple[float, int, list[Path]]] = []
        for md in root.glob("*.md"):
            meta = md.with_suffix(".json")
            paths = [md] + ([meta] if meta.exists() else [])
            try:
                mtime = md.stat().st_mtime
                size = sum(p.stat().st_size for p in paths)
            except OSError:
                continue
            entries.append((mtime, size, paths))
        for meta in root.glob("*.json"):
            # Orphaned metadata (interrupted write / partial eviction).
            if not meta.with_suffix(".md").exists():
                try:
                    meta.unlink()
                except OSError:
                    pass

        def _drop(entry: tuple[float, int, list[Path]]) -> None:
            nonlocal removed
            for p in entry[2]:
                try:
                    p.unlink()
                except OSError:
                    pass
            removed += 1

        entries.sort(key=lambda e: e[0])           # oldest first
        cutoff = time.time() - max_age_days * 86400
        keep: list[tuple[float, int, list[Path]]] = []
        for entry in entries:
            if entry[0] < cutoff:
                _drop(entry)
            else:
                keep.append(entry)
        total = sum(e[1] for e in keep)
        for entry in keep:                          # still oldest first
            if total <= max_bytes:
                break
            _drop(entry)
            total -= entry[1]
    except Exception as e:
        logger.warning("Cache eviction failed: %s", e)
    return removed

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


def _format_run_stats(run_stats: dict) -> list[str]:
    """
    Render the optional 'Run statistics' block appended to the report.
    run_stats = {"total_seconds": float, "agents": [{"agent", "seconds",
    "prompt_eval_count", "eval_count", "eval_duration", "restored"}, ...]}
    — every counter may be missing/None; render only what exists.
    """
    lines: list[str] = ["## Run Statistics", ""]
    total = run_stats.get("total_seconds")
    if total is not None:
        mins, secs = divmod(int(total), 60)
        lines.append(f"- **Total time:** {mins}m {secs}s")
    agents = run_stats.get("agents") or []
    total_prefill = sum(a.get("prompt_eval_count") or 0 for a in agents)
    total_gen = sum(a.get("eval_count") or 0 for a in agents)
    total_gen_ns = sum(a.get("eval_duration") or 0 for a in agents)
    if total_prefill:
        lines.append(f"- **Total prefill:** {total_prefill:,} tokens")
    if total_gen:
        lines.append(f"- **Total generated:** {total_gen:,} tokens")
    if total_gen and total_gen_ns:
        lines.append(
            f"- **Average speed:** {total_gen / (total_gen_ns / 1e9):.1f} tok/s"
        )
    if agents:
        lines += [
            "",
            "| Agent | Time | Prefill (tok) | Generated (tok) | Speed |",
            "|---|---|---|---|---|",
        ]
        for a in agents:
            if a.get("restored"):
                lines.append(
                    f"| {a.get('agent', '?')} | — | — | — | (cache) |"
                )
                continue
            secs = a.get("seconds")
            ec, ed = a.get("eval_count"), a.get("eval_duration")
            speed = f"{ec / (ed / 1e9):.1f} tok/s" if ec and ed else "—"
            pc = a.get("prompt_eval_count")
            lines.append(
                f"| {a.get('agent', '?')} "
                f"| {f'{secs:.0f}s' if secs is not None else '—'} "
                f"| {f'{pc:,}' if pc is not None else '—'} "
                f"| {f'{ec:,}' if ec is not None else '—'} "
                f"| {speed} |"
            )
    lines += ["", "---", ""]
    return lines


def build_report(
    agent_outputs: list[str],
    manuscript_data: dict,
    journal: str,
    model: str,
    output_dir: Path | None = None,
    run_stats: dict | None = None,
) -> Path:
    """
    Assemble all 6 agent outputs into a single Markdown report.
    Saves to output_dir (defaults to CWD) as PRE_SUBMISSION_MEDICAL_REVIEW_YYYY-MM-DD.md.
    Optionally appends a 'Run Statistics' block when run_stats is given.
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

    if run_stats:
        lines += _format_run_stats(run_stats)

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
