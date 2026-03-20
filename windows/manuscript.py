"""
manuscript.py — Manuscript discovery and reading (.tex / .md / .docx / .txt)
"""

import re
from pathlib import Path


def read_file(path: str | Path) -> str:
    """Read a plain-text file as UTF-8."""
    return Path(path).read_text(encoding="utf-8", errors="replace")


def read_docx(path: str | Path) -> str:
    """Extract plain text from a .docx file (requires python-docx)."""
    try:
        from docx import Document  # type: ignore
    except ImportError:
        raise ImportError(
            "python-docx is required to read .docx files.\n"
            "Install it with:  pip install python-docx"
        )
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def read_tex_recursive(path: str | Path, _visited: set | None = None) -> str:
    """
    Read a .tex file and recursively resolve \\input{}, \\include{}, \\subfile{}.
    Tracks visited paths to avoid infinite loops.
    """
    path = Path(path).resolve()
    if _visited is None:
        _visited = set()
    if path in _visited:
        return ""
    _visited.add(path)

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"% [Could not read {path}: {e}]\n"

    def _replace_include(match):
        directive = match.group(1)  # input / include / subfile
        arg = match.group(2).strip()
        # Resolve relative to the current file's directory
        candidate = (path.parent / arg).resolve()
        # Try adding .tex extension if needed
        if not candidate.exists() and not arg.endswith(".tex"):
            candidate = (path.parent / (arg + ".tex")).resolve()
        if candidate.exists():
            return f"\n% --- begin {candidate.name} ---\n" + read_tex_recursive(
                candidate, _visited
            ) + f"\n% --- end {candidate.name} ---\n"
        return match.group(0)  # leave unchanged if file not found

    pattern = re.compile(
        r"\\(input|include|subfile)\{([^}]+)\}", re.IGNORECASE
    )
    return pattern.sub(_replace_include, text)


def discover_manuscript(file_path: str | None = None) -> dict:
    """
    Locate and load the manuscript.

    If file_path is given, use it directly.
    Otherwise, search CWD for .tex or .md files (prefer .tex).

    Returns:
        {
            "title": str,
            "full_text": str,
            "figure_files": list[str],
            "table_files": list[str],
            "source_path": str,
        }
    """
    cwd = Path.cwd()

    # ---- Resolve the main file ----
    if file_path:
        main_file = Path(file_path).resolve()
        if not main_file.exists():
            raise FileNotFoundError(f"Manuscript not found: {main_file}")
    else:
        # Auto-detect: prefer .tex, then .md, then .docx
        tex_files = sorted(cwd.glob("*.tex"))
        md_files = sorted(cwd.glob("*.md"))
        docx_files = sorted(cwd.glob("*.docx"))
        candidates = tex_files or md_files or docx_files
        if not candidates:
            raise FileNotFoundError(
                f"No .tex, .md, or .docx manuscript found in {cwd}"
            )
        main_file = candidates[0]

    suffix = main_file.suffix.lower()

    # ---- Read content ----
    if suffix == ".tex":
        full_text = read_tex_recursive(main_file)
    elif suffix == ".docx":
        full_text = read_docx(main_file)
    else:
        full_text = read_file(main_file)

    # ---- Derive title ----
    title = _extract_title(full_text, suffix) or main_file.stem

    # ---- Find figures and tables alongside the manuscript ----
    base_dir = main_file.parent
    figure_exts = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg", ".tif", ".tiff"}
    figure_files = [
        str(p) for p in base_dir.iterdir()
        if p.suffix.lower() in figure_exts
    ]

    table_files: list[str] = []
    # Tables embedded in separate .tex files or .csv
    for p in base_dir.iterdir():
        name_lower = p.name.lower()
        if "table" in name_lower and p.suffix.lower() in {".tex", ".md", ".csv"}:
            table_files.append(str(p))

    return {
        "title": title,
        "full_text": full_text,
        "figure_files": figure_files,
        "table_files": table_files,
        "source_path": str(main_file),
    }


def _extract_title(text: str, suffix: str) -> str:
    """Best-effort title extraction from LaTeX or Markdown."""
    if suffix == ".tex":
        m = re.search(r"\\title\{([^}]+)\}", text, re.DOTALL)
        if m:
            # Strip nested LaTeX commands
            return re.sub(r"\\[a-zA-Z]+\{?", "", m.group(1)).strip()
    else:
        # Markdown: first level-1 heading
        m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    return ""
