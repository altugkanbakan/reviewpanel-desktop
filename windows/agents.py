"""
agents.py — 6 agent prompt builders + Ollama runner
"""

import sys
from pathlib import Path

import ollama

# ---------------------------------------------------------------------------
# Knowledge-base loader
# ---------------------------------------------------------------------------

KB_BASE = Path(__file__).parent / "knowledge_base"

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
            print(f"[WARNING] Could not load KB file {path}: {e}", file=sys.stderr)
            kb[key] = ""
    return kb


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

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
        "rules defined in your knowledge base files below. Identify stigmatizing "
        "language, non-SI units, and incorrect abbreviation usage.\n\n"
        "Output: A Markdown report with three sections:\n"
        "- **Critical Issues** (numbered list)\n"
        "- **Minor Issues** (numbered list)\n"
        "- **Style Patterns** (numbered list)"
    ),
    2: (
        "Verify internal coherence. Check whether numbers in the abstract match "
        "the main text and tables. Validate PICO consistency and check for sample "
        "attrition or leaky data flows. Use the STROBE and CONSORT guidelines "
        "provided to assess reporting completeness for the study design.\n\n"
        "Output: A Markdown report with three sections:\n"
        "- **Critical Inconsistencies** (numbered list)\n"
        "- **Sample Flow Errors** (numbered list)\n"
        "- **Terminology Drift** (numbered list)"
    ),
    3: (
        "Enforce claim discipline. Flag causal language ('causes', 'impacts', "
        "'leads to', 'results in') used in observational studies. Demand "
        "associative language instead. Differentiate between clinical and "
        "statistical significance. Flag unaddressed confounding biases.\n\n"
        "Output: A Markdown report with three sections:\n"
        "- **Causal Overclaiming** (numbered list)\n"
        "- **Clinical/Statistical Conflation** (numbered list)\n"
        "- **Missing Caveats** (numbered list)"
    ),
    4: (
        "Enforce SAMPL guidelines (provided below). Check appropriateness of "
        "statistical tests, presence of exact p-values, and 95% CIs for all point "
        "estimates. Verify missing data handling and power calculations.\n\n"
        "Output: A Markdown report with three sections:\n"
        "- **Methodological Errors** (numbered list)\n"
        "- **Incomplete Statistical Reporting** (numbered list)\n"
        "- **Regression Issues** (numbered list)"
    ),
    5: (
        "Verify tables and figures. Check Table 1 (Baseline Characteristics). "
        "Ensure STROBE/CONSORT patient flow diagrams are mathematically correct. "
        "Check axis scaling (log scale for OR/HR). Verify all referenced figures "
        "and tables exist and are properly labelled.\n\n"
        "Output: A Markdown report with two sections:\n"
        "- **Missing Elements in Tables/Figures** (numbered list)\n"
        "- **Formatting Inconsistencies** (numbered list)"
    ),
    6: (
        "Evaluate translational value and scientific rigor based entirely on the "
        "desk-reject triggers and methodology requirements defined in the journal "
        "profile provided (if any). If no profile is provided, apply top-tier "
        "general medical journal standards.\n\n"
        "Output a Markdown report with six parts:\n"
        "**Part 1 — Central Contribution Rating** (1–10 scale with justification)\n"
        "**Part 2 — Methodological Credibility** (key strengths and fatal flaws)\n"
        "**Part 3 — Required / Suggested Analyses** (numbered list)\n"
        "**Part 4 — Literature Positioning** (how paper fits existing evidence)\n"
        "**Part 5 — Recommendation** (one of: Send to referees / Major revision / "
        "Desk reject) with one-paragraph justification\n"
        "**Part 6 — Questions to Authors** (4–7 rigorous questions)"
    ),
}


def build_prompt(
    agent_num: int,
    manuscript_text: str,
    kb: dict[str, str],
    journal_profile_text: str = "",
) -> str:
    """Build the full prompt for a given agent."""
    role = _AGENT_ROLES[agent_num]
    task = _AGENT_TASKS[agent_num]

    sections: list[str] = []

    sections.append(
        f"You are acting as a {role} reviewing an academic medical manuscript.\n"
        f"Your agent number is {agent_num} of 6."
    )

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

    elif agent_num == 6 and journal_profile_text:
        sections.append(
            "## Target Journal Profile\n\n" + journal_profile_text
        )

    # ---- Manuscript ----
    sections.append("## Manuscript\n\n" + manuscript_text)

    # ---- Task instructions ----
    sections.append("## Your Task\n\n" + task)

    return "\n\n---\n\n".join(sections)


# ---------------------------------------------------------------------------
# Ollama runner
# ---------------------------------------------------------------------------

def run_agent(
    agent_num: int,
    prompt: str,
    model: str = "qwen2.5:7b",
    verbose: bool = False,
) -> str:
    """
    Send the prompt to Ollama and return the model's response text.
    Uses low temperature (0.3) for consistent structured Markdown output.
    """
    if verbose:
        print(
            f"  [Agent {agent_num}] Sending prompt "
            f"({len(prompt):,} chars) to {model} ...",
            flush=True,
        )

    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"num_ctx": 32768, "temperature": 0.3},
    )
    content: str = response["message"]["content"]

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
    """
    kb = load_knowledge_base()
    outputs: list[str] = []
    manuscript_text = manuscript_data["full_text"]

    for agent_num in range(1, 7):
        name = _AGENT_NAMES[agent_num]
        print(f"[{agent_num}/6] Running Agent {agent_num}: {name} ...", flush=True)

        prompt = build_prompt(
            agent_num,
            manuscript_text,
            kb,
            journal_profile_text if agent_num == 6 else "",
        )
        result = run_agent(agent_num, prompt, model=model, verbose=verbose)
        outputs.append(result)

        print(f"[{agent_num}/6] Agent {agent_num} complete.", flush=True)

    return outputs
