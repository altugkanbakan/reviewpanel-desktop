"""
agents.py — 6 agent prompt builders + Ollama runner
"""

import logging
import re
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import ollama

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Knowledge-base loader
# ---------------------------------------------------------------------------

# Single source of truth for the KB location (frozen-build aware): core.py
from core import KB_BASE

_KB_FILES = {
    "ama_style": KB_BASE / "standarts" / "AMA_Style_Core_Guidelines.md",
    "patient_first": KB_BASE / "standarts" / "patient_first_terminology.csv",
    "strobe": KB_BASE / "guidelines" / "STROBE_guidelines.md",
    "consort": KB_BASE / "guidelines" / "CONSORT_guidelines.md",
    "sampl": KB_BASE / "guidelines" / "SAMPL_guidelines.md",
}


def load_knowledge_base() -> dict[str, str]:
    """Read all KB files at startup; return dict keyed by short name."""
    kb: dict[str, str] = {}
    for key, path in _KB_FILES.items():
        try:
            kb[key] = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning("Could not load KB file %s: %s", path, e)
            kb[key] = ""
    return kb


def verify_knowledge_base() -> list[str]:
    """
    Integrity check: return the KB keys whose files are missing, unreadable
    or empty. An empty list means every expected KB file loaded with content.
    Callers should surface a *visible* warning when this is non-empty —
    load_knowledge_base() deliberately keeps its silent empty-string
    fallback so a damaged install still runs, but that fallback silently
    produces worthless reviews if nobody checks this.
    """
    problems: list[str] = []
    for key, path in _KB_FILES.items():
        try:
            if not path.read_text(encoding="utf-8", errors="replace").strip():
                problems.append(key)
        except OSError:
            problems.append(key)
    if problems:
        logger.warning(
            "Knowledge base incomplete — missing/empty: %s (KB_BASE=%s)",
            ", ".join(problems), KB_BASE,
        )
    return problems


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

# Version stamp of the prompt templates below. core.cache_key() mixes this
# into every cache key, so BUMP IT BY HAND whenever _AGENT_ROLES,
# _AGENT_TASKS or the structure build_prompt() emits changes in any way
# that alters the text sent to the model — otherwise outputs generated
# with the old prompts would be served from the cache as if the new
# prompts had produced them: a silent, hard-to-spot corruption.
PROMPT_VERSION = 2

_AGENT_ROLES = {
    1: "strict copy editor",
    2: "technical reviewer",
    3: "skeptical clinical epidemiologist",
    4: "biostatistician",
    5: "production editor",
    6: "demanding associate editor",
}

_AGENT_TASKS = {
    1: (
        "Perform a thorough review of the manuscript prose based strictly on the "
        "rules defined in your knowledge base files above.\n\n"
        "CRITICAL RULES — you must follow these exactly:\n"
        "1. ONLY flag a term if it appears verbatim in the manuscript text above. "
        "For every finding, you MUST quote the exact sentence or phrase from the "
        "manuscript that contains the problem. If you cannot provide a direct "
        "quote, do not report the finding.\n"
        "2. Before reviewing, identify the manuscript type (e.g. clinical case "
        "report, RCT, observational study, AI/computational evaluation, review "
        "article). Apply rules marked 'clinical_only' only to clinical care "
        "writing and case reports — NOT to research methods or AI evaluation "
        "papers. Apply rules marked 'observational_only' only to observational "
        "studies, not to RCTs or experimental/computational studies.\n"
        "3. Do not invent, assume, or infer errors. If you are unsure whether a "
        "term is present, skip it.\n"
        "4. SEVERITY — place each finding in exactly one section:\n"
        "   - Critical Issues: ONLY problems that change or obscure the "
        "scientific meaning: contradictory or wrong numbers in prose, grammar "
        "so ambiguous the finding could be misread, wrong units or "
        "abbreviations that could cause misinterpretation. Terminology, "
        "word-choice and inclusive-language findings are NEVER Critical, no "
        "matter how often they occur.\n"
        "   - Minor Issues: objective AMA formatting errors that do not change "
        "meaning (number style, abbreviation expansion, eponym possessives, "
        "reference format), plus CSV rows whose severity column reads "
        "'minor'.\n"
        "   - Style Patterns: ALL findings that come from the Patient-First "
        "Terminology CSV, and all wording/tone preferences. Use the CSV's "
        "severity and rule_category columns: rows marked 'suggestion' belong "
        "here.\n"
        "5. AGGREGATE: if the same term or pattern occurs more than once, "
        "report it as ONE item — the term, the total number of occurrences, "
        "ONE example quote, and the suggested replacement. Never write one "
        "item per occurrence.\n"
        "6. Report at most 5 Critical Issues, 8 Minor Issues, and 8 Style "
        "Patterns, most important first. If a section has no findings, write "
        "\"None found.\"\n\n"
        "Output: A Markdown report with three sections:\n"
        "- **Critical Issues** (numbered list — each item must include a direct "
        "quote from the manuscript)\n"
        "- **Minor Issues** (numbered list — each item must include a direct "
        "quote from the manuscript)\n"
        "- **Style Patterns** (numbered list — aggregated terminology and tone "
        "patterns, one item per term with occurrence count)"
    ),
    2: (
        "Verify internal coherence. Check whether numbers in the abstract match "
        "the main text and tables. Validate PICO consistency and check for sample "
        "attrition or leaky data flows.\n\n"
        "CRITICAL RULES:\n"
        "1. First, identify the study design (RCT, observational cohort, "
        "diagnostic accuracy, AI/computational evaluation, systematic review, "
        "etc.). State this at the top of your report.\n"
        "2. Apply CONSORT guidelines ONLY if the study is an RCT. Do NOT demand "
        "randomization flow diagrams, allocation concealment, or blinding for "
        "non-RCT study designs.\n"
        "3. Apply STROBE guidelines ONLY if the study is observational "
        "(cohort, case-control, cross-sectional).\n"
        "4. For AI/computational evaluation studies, check for: dataset "
        "description completeness, test/validation split reporting, and "
        "consistency between reported metrics. Do not apply clinical trial "
        "checklists.\n"
        "5. Only flag inconsistencies you can document with specific numbers or "
        "quotes from both locations (e.g. 'Abstract states X but Methods "
        "states Y').\n"
        "6. Terminology Drift means the SAME concept is called different names "
        "in different places (e.g. \"emergency department\" vs \"emergency "
        "room\") in a way that could confuse the reader. Do not comment on "
        "word choice, style, or inclusive language — that is another "
        "reviewer's job. One item per drifting concept, listing the variants. "
        "Report at most 5 items per section.\n\n"
        "Output: A Markdown report with three sections:\n"
        "- **Critical Inconsistencies** (numbered list, with quotes from both "
        "locations for each item)\n"
        "- **Sample Flow Errors** (numbered list — only applicable to the "
        "identified study design)\n"
        "- **Terminology Drift** (numbered list)"
    ),
    3: (
        "Enforce claim discipline. Flag causal language ('causes', 'impacts', "
        "'leads to', 'results in') used in observational studies. Demand "
        "associative language instead. Differentiate between clinical and "
        "statistical significance. Flag unaddressed confounding biases.\n\n"
        "CRITICAL RULES:\n"
        "1. First identify the study design and state it at the top of your "
        "report. Flag causal language ONLY if the design is observational "
        "(cohort, case-control, cross-sectional). In RCTs and experimental "
        "studies, causal language is appropriate — do not flag it.\n"
        "2. For every finding in Causal Overclaiming, you MUST "
        "provide (a) the exact original sentence quoted from the manuscript, "
        "and (b) a revised version using appropriate associative language. "
        "The revised sentence MUST be meaningfully different from the original "
        "— do not repeat the original text as the suggested fix.\n"
        "3. If the same causal verb appears in many sentences, report the 3 "
        "clearest examples and state the total count — do not list every "
        "occurrence. Report at most 5 items per section, ordered by how much "
        "the claim overstates the evidence. If a section has no findings, "
        "write \"None found.\"\n\n"
        "Output: A Markdown report with three sections:\n"
        "- **Causal Overclaiming** (numbered list — each item: original quote, "
        "then suggested revision)\n"
        "- **Clinical/Statistical Conflation** (numbered list)\n"
        "- **Missing Caveats** (numbered list)"
    ),
    4: (
        "Enforce SAMPL guidelines (provided above). Check appropriateness of "
        "statistical tests, presence of exact p-values, and 95% CIs for all point "
        "estimates. Verify missing data handling and power calculations.\n\n"
        "Output: A Markdown report with three sections:\n"
        "- **Methodological Errors** (numbered list)\n"
        "- **Incomplete Statistical Reporting** (numbered list)\n"
        "- **Regression Issues** (numbered list)\n\n"
        "CRITICAL RULES:\n"
        "1. For every finding, quote the specific statistic, test name, or "
        "sentence from the manuscript. Do not report a SAMPL item as missing "
        "unless you looked for it and it is absent from the text.\n"
        "2. If the manuscript contains no regression analysis, write \"Not "
        "applicable — no regression reported\" under Regression Issues "
        "instead of inventing findings.\n"
        "3. Report at most 6 items per section, most consequential first. If "
        "a section has no findings, write \"None found.\""
    ),
    5: (
        "Verify tables and figures. Check Table 1 (Baseline Characteristics). "
        "Ensure STROBE/CONSORT patient flow diagrams are mathematically correct. "
        "Check axis scaling (log scale for OR/HR). Verify all referenced figures "
        "and tables exist and are properly labelled.\n\n"
        "CRITICAL RULES:\n"
        "1. PLAIN TEXT LIMITATION: This manuscript was extracted from a .docx "
        "file. Embedded tables, figures, and images are NOT visible in the text "
        "you receive — only their captions or titles may appear as paragraph "
        "text. Do NOT flag a table or figure as missing solely because its data "
        "rows are absent from the plain text. Only flag structural absence when "
        "the manuscript text itself says the element exists but you find no "
        "caption or reference to it anywhere.\n"
        "2. CONSISTENCY: Do not simultaneously describe the same element as "
        "both present and absent. If uncertain, state the limitation explicitly "
        "rather than making a definitive claim.\n"
        "3. Only report elements as absent if you are confident they are "
        "structurally missing — not merely invisible due to plain-text "
        "extraction.\n\n"
        "Output: A Markdown report with two sections:\n"
        "- **Missing Elements in Tables/Figures** (numbered list — only items "
        "you are confident are structurally absent)\n"
        "- **Formatting Inconsistencies** (numbered list)\n\n"
        "Report at most 5 items per section. If a section has no findings, "
        "write \"None found.\""
    ),
    6: (
        "Evaluate translational value and scientific rigor based entirely on the "
        "desk-reject triggers and methodology requirements defined in the journal "
        "profile provided (if any). If no journal profile is provided, "
        "evaluate against top-tier general medical journal standards "
        "(JAMA / NEJM / Lancet class): generalizable evidence, strict "
        "adherence to the appropriate reporting guideline (CONSORT for RCTs, "
        "STROBE for observational studies), 95% CIs with exact p-values, and "
        "a clear clinical bottom line. Base your recommendation ONLY on "
        "scientific validity and clinical impact — never on style or "
        "terminology.\n\n"
        "You have also been given the outputs of Agents 1–5 above. Use these to "
        "inform your synthesis in Part 7.\n\n"
        "Output a Markdown report with seven parts:\n"
        "**Part 1 — Central Contribution Rating** (1–10 scale with justification)\n"
        "**Part 2 — Methodological Credibility** (key strengths and fatal flaws)\n"
        "**Part 3 — Required / Suggested Analyses** (numbered list)\n"
        "**Part 4 — Literature Positioning** (how paper fits existing evidence)\n"
        "**Part 5 — Recommendation** (one of: Send to referees / Major revision / "
        "Desk reject) with one-paragraph justification\n"
        "**Part 6 — Questions to Authors** (4–7 rigorous questions)\n"
        "**Part 7 — Priority Action Items** (synthesised from ALL agent outputs "
        "above, including your own evaluation): Triage all issues into three "
        "groups — **Critical** (must fix before any referee sees this), "
        "**Major** (must address in revision), **Minor** (should address). "
        "Each item must state which domain it comes from (e.g. Style, "
        "Statistics, Clinical Claims). This section must never be empty. "
        "Severity calibration: Critical and Major are reserved for problems "
        "that undermine the validity or interpretation of the results (wrong "
        "or inconsistent numbers, methodological flaws, unsupported causal "
        "claims, missing key analyses). Style, grammar, terminology and "
        "inclusive-language findings are at most Minor — never Critical or "
        "Major. If two agents reported the same underlying issue, merge them "
        "into one item."
    ),
}


def build_prompt(
    agent_num: int,
    manuscript_text: str,
    kb: dict[str, str],
    journal_profile_text: str = "",
    previous_outputs: list[str] | None = None,
) -> str:
    """Build the full prompt for a given agent."""
    role = _AGENT_ROLES[agent_num]
    task = _AGENT_TASKS[agent_num]

    sections: list[str] = []

    # ---- Manuscript ----
    # Always first and byte-identical across all 6 agents (no agent number,
    # role, or other variable content before or inside this block) so
    # Ollama's prefix KV cache can reuse the prefill between agent calls.
    sections.append("## Manuscript\n\n" + manuscript_text)

    # ---- Inject knowledge-base files ----
    if agent_num == 1:
        sections.append(
            "## AMA Style Core Guidelines\n\n" + kb.get("ama_style", "")
        )
        sections.append(
            "## Patient-First Terminology (CSV)\n\n" + kb.get("patient_first", "")
        )

    elif agent_num == 2:
        sections.append(
            "## STROBE Guidelines\n\n" + kb.get("strobe", "")
        )
        sections.append(
            "## CONSORT Guidelines\n\n" + kb.get("consort", "")
        )

    elif agent_num == 4:
        sections.append(
            "## SAMPL Guidelines\n\n" + kb.get("sampl", "")
        )

    elif agent_num == 6:
        if journal_profile_text:
            sections.append(
                "## Target Journal Profile\n\n" + journal_profile_text
            )
        if previous_outputs:
            agent_names = [
                "Agent 1 — Medical Style & Grammar",
                "Agent 2 — Internal Consistency & PICO",
                "Agent 3 — Clinical Claims & Causality",
                "Agent 4 — Biostatistics & Methodology",
                "Agent 5 — Tables, Figures & Documentation",
            ]
            blocks = "\n\n---\n\n".join(
                f"### {agent_names[i]}\n\n{out.strip()}"
                for i, out in enumerate(previous_outputs)
            )
            sections.append("## Previous Agent Outputs\n\n" + blocks)

    # ---- Role + task instructions (last, for instruction recency) ----
    sections.append(
        f"You are acting as a {role} reviewing the academic medical "
        f"manuscript above.\n"
        f"Your agent number is {agent_num} of 6."
    )
    sections.append("## Your Task\n\n" + task)

    return "\n\n---\n\n".join(sections)


# ---------------------------------------------------------------------------
# Ollama runner
# ---------------------------------------------------------------------------

# Per-request timeout in seconds. A single agent can legitimately take
# 1–5 minutes on slow hardware, so be generous before giving up.
_REQUEST_TIMEOUT = 900

# How many retries after the first failed attempt (network/timeout errors).
_MAX_RETRIES = 1

# Seconds to wait before retrying.
_RETRY_DELAY = 5

# Default / ceiling context window. Callers should size the window per run
# via plan_context(); this value is only the fallback and the ladder top.
_NUM_CTX = 32768

# Context-window sizing. Ollama reloads the model — and drops its prefix KV
# cache — whenever num_ctx changes, so a run uses at most two values: one for
# agents 1–5 (tier A) and one for agent 6 (tier B).
#
# The window is rounded up to a _CTX_STEP multiple rather than a power of two:
# llama.cpp allocates KV cache for the whole window, and on a 6 GB card every
# unused token costs real VRAM (~56 KiB/token for a 7B GQA model). Rounding
# 17,700 up to 32,768 instead of 18,432 would waste ~800 MiB and push the
# model off the GPU — the exact spill this sizing exists to avoid.
_CTX_MIN = 4096
_CTX_STEP = 2048
_CTX_MAX = 32768

# Tokens reserved for the model's own output when sizing the context window.
_CTX_RESERVE = 2048

# Keep the model loaded between agent calls so the prefix KV cache survives.
# Verified against ollama 0.6.1: Client.chat(..., keep_alive=...) exists.
_KEEP_ALIVE = "30m"

# Minimum seconds between on_chunk callbacks (~5 GUI updates per second).
_STREAM_MIN_INTERVAL = 0.2


def _estimate_tokens(text: str) -> int:
    """Rough heuristic token estimate (~4 characters per token)."""
    return len(text) // 4


def plan_context(prompt_tokens: int, reserve: int = _CTX_RESERVE) -> int:
    """
    Round prompt_tokens + reserve up to the next _CTX_STEP multiple, clamped
    to [_CTX_MIN, _CTX_MAX]. Returns _CTX_MAX when even that is too small.
    """
    needed = prompt_tokens + reserve
    if needed <= _CTX_MIN:
        return _CTX_MIN
    stepped = -(-needed // _CTX_STEP) * _CTX_STEP   # ceil to step multiple
    return min(stepped, _CTX_MAX)


# ---------------------------------------------------------------------------
# Agent 6 diet — budget-driven, content-aware trimming of previous outputs
# ---------------------------------------------------------------------------

# Section markers that may be dropped when the Agent 6 prompt must shrink,
# ordered lowest priority first. Mirrors core._EXPECTED_MARKERS; critical
# sections (Critical Issues, Critical Inconsistencies, Causal Overclaiming,
# Methodological Errors, Missing Elements in Tables/Figures) are never
# dropped wholesale — at worst they are tail-truncated as a last resort.
_TRIM_DROP_ORDER = (
    "Style Patterns",
    "Minor Issues",
    "Terminology Drift",
    "Formatting Inconsistencies",
    "Missing Caveats",
    "Regression Issues",
    "Incomplete Statistical Reporting",
    "Sample Flow Errors",
    "Clinical/Statistical Conflation",
)

# No agent's output may be trimmed below this many (estimated) tokens.
_TRIM_MIN_TOKENS = 256

_TRIM_NOTICE = "\n\n[... trimmed to fit the context window ...]"

# A Markdown heading line: "## Title" or a line that is only "**Title**".
_HEADING_RE = re.compile(r"^(#{1,6}\s+.+|\*\*[^*]+\*\*:?\s*)$")


def _split_blocks(text: str) -> list[tuple[str, str]]:
    """
    Split a Markdown agent output into (heading, block_text) tuples, where
    heading is the lower-cased heading line ("" for the preamble) and
    block_text includes the heading line itself.
    """
    headings: list[str] = [""]
    blocks: list[list[str]] = [[]]
    for line in text.splitlines():
        stripped = line.strip()
        if _HEADING_RE.match(stripped):
            headings.append(stripped.lower())
            blocks.append([line])
        else:
            blocks[-1].append(line)
    result = [
        (h, "\n".join(b)) for h, b in zip(headings, blocks)
        if h or "\n".join(b).strip()
    ]
    return result or [("", text)]


def _trim_one(text: str, budget_tokens: int) -> str:
    """
    Trim a single agent output to roughly budget_tokens. Content-aware:
    drops low-priority sections first; falls back to head truncation
    (keep the beginning, cut the tail) when no heading structure exists.
    """
    if _estimate_tokens(text) <= budget_tokens:
        return text

    blocks = _split_blocks(text)
    trimmed = text
    if len(blocks) > 1:
        for marker in _TRIM_DROP_ORDER:
            key = marker.lower()
            kept = [b for b in blocks if not (b[0] and key in b[0])]
            if len(kept) == len(blocks):
                continue
            blocks = kept
            trimmed = "\n\n".join(b[1].strip("\n") for b in blocks)
            if _estimate_tokens(trimmed + _TRIM_NOTICE) <= budget_tokens:
                return trimmed + _TRIM_NOTICE
    if _estimate_tokens(trimmed + _TRIM_NOTICE) <= budget_tokens:
        return trimmed + _TRIM_NOTICE

    # Head truncation: keep the beginning (critical sections come first).
    keep_chars = max(
        (budget_tokens - _estimate_tokens(_TRIM_NOTICE)) * 4,
        _TRIM_MIN_TOKENS * 4,
    )
    return trimmed[:keep_chars].rstrip() + _TRIM_NOTICE


def trim_previous_outputs(outputs: list[str], budget_tokens: int) -> list[str]:
    """
    Fit the previous agents' outputs into ~budget_tokens (estimated).
    The budget is shared by water-filling: outputs already below their
    fair share keep everything, and their leftover budget is given to
    the larger outputs. No output is ever removed entirely — each one
    keeps at least _TRIM_MIN_TOKENS. Returns a new list.
    """
    if not outputs:
        return []
    sizes = [_estimate_tokens(o) for o in outputs]
    if sum(sizes) <= budget_tokens:
        return list(outputs)

    pool = max(budget_tokens, _TRIM_MIN_TOKENS * len(outputs))
    remaining = list(range(len(outputs)))
    shares: dict[int, int] = {}
    changed = True
    while remaining and changed:
        changed = False
        fair = pool // len(remaining)
        for i in list(remaining):
            if sizes[i] <= fair:
                shares[i] = sizes[i]
                pool -= sizes[i]
                remaining.remove(i)
                changed = True
    for i in remaining:
        shares[i] = max(pool // len(remaining), _TRIM_MIN_TOKENS)

    return [
        outputs[i] if shares[i] >= sizes[i] else _trim_one(outputs[i], shares[i])
        for i in range(len(outputs))
    ]


def prepare_agent6_prompt(
    manuscript_text: str,
    kb: dict[str, str],
    journal_profile_text: str,
    previous_outputs: list[str],
    tier_a_ctx: int,
    reserve: int = _CTX_RESERVE,
) -> tuple[str, int, dict]:
    """
    Build the Agent 6 prompt under the two-tier context policy.

    Prefer tier_a_ctx, so the whole run uses a single num_ctx and the model
    is never reloaded: keep the outputs whole if they fit there, otherwise
    trim them to that budget. Only when even minimally trimmed outputs
    cannot fit does the window grow — sized to what is actually needed.
    Returns (prompt, num_ctx, info) where info = {"trimmed",
    "before_tokens", "after_tokens", "num_ctx"} for logging.
    """
    base_prompt = build_prompt(6, manuscript_text, kb, journal_profile_text, None)
    base_tokens = _estimate_tokens(base_prompt)
    full_prompt = build_prompt(
        6, manuscript_text, kb, journal_profile_text, previous_outputs
    )
    full_tokens = _estimate_tokens(full_prompt)

    def _info(trimmed: bool, after: int, ctx: int) -> dict:
        return {
            "trimmed": trimmed,
            "before_tokens": full_tokens,
            "after_tokens": after,
            "num_ctx": ctx,
        }

    # Everything fits as-is at tier A: no trim, no reload.
    if full_tokens + reserve <= tier_a_ctx:
        return full_prompt, tier_a_ctx, _info(False, full_tokens, tier_a_ctx)

    # Trim to tier A's budget when the shares are still meaningful.
    budget = tier_a_ctx - reserve - base_tokens
    if budget >= _TRIM_MIN_TOKENS * len(previous_outputs):
        trimmed = trim_previous_outputs(previous_outputs, budget)
        prompt = build_prompt(
            6, manuscript_text, kb, journal_profile_text, trimmed
        )
        prompt_tokens = _estimate_tokens(prompt)
        if prompt_tokens + reserve <= tier_a_ctx:
            return prompt, tier_a_ctx, _info(True, prompt_tokens, tier_a_ctx)

    # Manuscript and knowledge base alone crowd out tier A: grow the window
    # to what minimally trimmed outputs actually need, and no further.
    trimmed = trim_previous_outputs(
        previous_outputs, _TRIM_MIN_TOKENS * len(previous_outputs)
    )
    prompt = build_prompt(6, manuscript_text, kb, journal_profile_text, trimmed)
    prompt_tokens = _estimate_tokens(prompt)
    ctx = max(tier_a_ctx, plan_context(prompt_tokens, reserve))
    if prompt_tokens + reserve <= ctx:
        # Spend whatever headroom that window left on longer outputs.
        budget = ctx - reserve - base_tokens
        if budget > _TRIM_MIN_TOKENS * len(previous_outputs):
            trimmed = trim_previous_outputs(previous_outputs, budget)
            wider = build_prompt(
                6, manuscript_text, kb, journal_profile_text, trimmed
            )
            if _estimate_tokens(wider) + reserve <= ctx:
                prompt, prompt_tokens = wider, _estimate_tokens(wider)
    return prompt, ctx, _info(True, prompt_tokens, ctx)


def _chunk_field(chunk, key: str):
    """Read a counter off a streamed chunk (ollama ChatResponse or dict)."""
    if chunk is None:
        return None
    try:
        return chunk.get(key)
    except AttributeError:
        return getattr(chunk, key, None)


def run_agent(
    agent_num: int,
    prompt: str,
    model: str = "qwen2.5:7b",
    verbose: bool = False,
    num_ctx: int | None = None,
    on_chunk: Callable[[str], None] | None = None,
    on_log: Callable[[str], None] | None = None,
    stats: dict | None = None,
) -> str:
    """
    Send the prompt to Ollama (streaming) and return the full response text.
    Uses low temperature (0.3) for consistent structured Markdown output.
    Retries once on network/timeout errors; raises RuntimeError (carrying
    the agent number) if all attempts fail.

    num_ctx  — context window for this call (defaults to _NUM_CTX so
               legacy call sites keep the old behaviour).
    on_chunk — optional progress callback, throttled to one call per
               _STREAM_MIN_INTERVAL seconds, invoked with the FULL text
               accumulated so far. An empty string means a retry has
               restarted the stream. Must not touch Tkinter directly —
               the GUI feeds its thread-safe queue here.
    on_log   — optional callback for human-readable notices (retries).
    stats    — optional dict, filled in-place with the final chunk's
               counters: prompt_eval_count, eval_count,
               prompt_eval_duration, eval_duration (ns; may be None).
    """
    ctx = num_ctx if num_ctx is not None else _NUM_CTX
    est_tokens = _estimate_tokens(prompt)
    if est_tokens > ctx:
        logger.warning(
            "Agent %d: prompt ~%d tokens exceeds context window (%d); "
            "output may be truncated",
            agent_num, est_tokens, ctx,
        )

    if verbose:
        print(
            f"  [Agent {agent_num}] Sending prompt "
            f"({len(prompt):,} chars, ~{est_tokens:,} tokens) to {model} "
            f"(num_ctx={ctx}) ...",
            flush=True,
        )

    client = ollama.Client(timeout=_REQUEST_TIMEOUT)
    content = ""
    final_chunk = None
    for attempt in range(_MAX_RETRIES + 1):
        parts: list[str] = []
        last_emit = 0.0
        try:
            stream = client.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                options={"num_ctx": ctx, "temperature": 0.3},
                stream=True,
                keep_alive=_KEEP_ALIVE,
            )
            for chunk in stream:
                piece = chunk["message"]["content"] or ""
                if piece:
                    parts.append(piece)
                final_chunk = chunk
                if on_chunk is not None:
                    now = time.monotonic()
                    if now - last_emit >= _STREAM_MIN_INTERVAL:
                        last_emit = now
                        on_chunk("".join(parts))
            content = "".join(parts)
            break
        except (httpx.TransportError, ConnectionError) as exc:
            final_chunk = None
            if attempt < _MAX_RETRIES:
                logger.warning(
                    "Agent %d: Ollama request failed (%s) — retrying in %ds "
                    "(attempt %d/%d)",
                    agent_num, exc, _RETRY_DELAY,
                    attempt + 1, _MAX_RETRIES + 1,
                )
                if on_log is not None:
                    on_log(f"[retry] restarting agent {agent_num}")
                if on_chunk is not None:
                    on_chunk("")  # reset any partial text shown in the GUI
                time.sleep(_RETRY_DELAY)
            else:
                raise RuntimeError(
                    f"Agent {agent_num}: Ollama request failed after "
                    f"{_MAX_RETRIES + 1} attempts: {exc}"
                ) from exc

    if on_chunk is not None:
        on_chunk(content)  # final flush with the complete text
    if stats is not None:
        for key in (
            "prompt_eval_count", "eval_count",
            "prompt_eval_duration", "eval_duration",
        ):
            stats[key] = _chunk_field(final_chunk, key)
        stats["num_ctx"] = ctx

    if verbose:
        print(
            f"  [Agent {agent_num}] Response received "
            f"({len(content):,} chars).",
            flush=True,
        )

    return content


# ---------------------------------------------------------------------------
# Sequential orchestrator
# ---------------------------------------------------------------------------

_AGENT_NAMES = {
    1: "Medical Style, Grammar & Reporting",
    2: "Internal Consistency & PICO Verification",
    3: "Clinical Claims, Causality & Confounding",
    4: "Biostatistics, Methodology & Notation",
    5: "Tables, Figures & Clinical Documentation",
    6: "Clinical Impact & Adversarial Referee",
}


def run_all_agents(
    manuscript_data: dict,
    journal: str,
    journal_profile_text: str,
    model: str = "qwen2.5:7b",
    verbose: bool = False,
) -> list[str]:
    """
    Run all 6 agents sequentially (VRAM constraint).
    Returns a list of 6 response strings (index 0 = Agent 1).

    Headless path; the GUI runs its own loop in gui.py::_thread_run.
    """
    kb = load_knowledge_base()
    outputs: list[str] = []
    manuscript_text = manuscript_data["full_text"]

    # Two-tier context policy: one num_ctx for agents 1-5 (tier A) and at
    # most one other for agent 6 (each num_ctx change reloads the model
    # and drops Ollama's prefix cache).
    prompts = {
        n: build_prompt(n, manuscript_text, kb, "", None) for n in range(1, 6)
    }
    tier_a_ctx = plan_context(
        max(_estimate_tokens(p) for p in prompts.values())
    )
    print(f"Context window: {tier_a_ctx} tokens (agents 1-5)", flush=True)

    for agent_num in range(1, 7):
        name = _AGENT_NAMES[agent_num]
        print(f"[{agent_num}/6] Running Agent {agent_num}: {name} ...", flush=True)

        if agent_num == 6:
            prompt, num_ctx, info = prepare_agent6_prompt(
                manuscript_text, kb, journal_profile_text, outputs, tier_a_ctx,
            )
            if info["trimmed"]:
                print(
                    f"Agent 6 input trimmed: {info['before_tokens']:,} "
                    f"→ {info['after_tokens']:,} tokens",
                    flush=True,
                )
            if num_ctx == tier_a_ctx:
                print(
                    f"Context window: {num_ctx} tokens (agent 6 — same as "
                    "agents 1-5, no model reload)",
                    flush=True,
                )
            else:
                print(f"Context window: {num_ctx} tokens (agent 6)", flush=True)
        else:
            prompt, num_ctx = prompts[agent_num], tier_a_ctx
        result = run_agent(
            agent_num, prompt, model=model, verbose=verbose, num_ctx=num_ctx,
        )
        outputs.append(result)

        print(f"[{agent_num}/6] Agent {agent_num} complete.", flush=True)

    return outputs
