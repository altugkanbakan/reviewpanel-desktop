"""
manuscript.py — Manuscript discovery and reading (.tex / .md / .docx / .pdf / .txt)

.docx and .pdf go through Microsoft MarkItDown's Docx/Pdf converters, which
keep headings and tables as Markdown. The converters are called directly
rather than through MarkItDown.convert(): that path silently falls back to a
plain-text converter on failure (returning a corrupt file's raw bytes as
"text") and would also enable optional cloud converters. Called this way,
conversion is fully offline. If MarkItDown is missing or fails on a .docx,
reading falls back to python-docx plain text.
"""

import re
from pathlib import Path

_converters = None


def _get_markitdown():
    """Return MarkItDown's local {suffix: converter} map (None if not installed)."""
    global _converters
    if _converters is None:
        try:
            from markitdown.converters import (  # type: ignore
                DocxConverter,
                PdfConverter,
            )
        except ImportError:
            return None
        _converters = {".docx": DocxConverter(), ".pdf": PdfConverter()}
    return _converters


def _convert_with_markitdown(path: Path) -> str | None:
    """Convert a .docx/.pdf to Markdown locally; None if unavailable or failed."""
    converters = _get_markitdown()
    if converters is None:
        return None
    suffix = path.suffix.lower()
    converter = converters.get(suffix)
    if converter is None:
        return None
    from markitdown import StreamInfo  # type: ignore
    try:
        with open(path, "rb") as stream:
            text = converter.convert(
                stream, StreamInfo(extension=suffix, local_path=str(path))
            ).markdown
    except Exception:
        return None
    return text if text and text.strip() else None


def read_file(path: str | Path) -> str:
    """Read a plain-text file as UTF-8."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise ValueError(f"Could not read file {path}: {e}") from e


def read_docx(path: str | Path) -> str:
    """Extract a .docx as Markdown (MarkItDown), else plain text (python-docx)."""
    converted = _convert_with_markitdown(Path(path))
    if converted is not None:
        return converted
    try:
        from docx import Document  # type: ignore
    except ImportError:
        raise ImportError(
            "python-docx is required to read .docx files.\n"
            "Install it with:  pip install python-docx"
        )
    try:
        doc = Document(str(path))
    except Exception as e:
        raise ValueError(
            f"Could not read .docx file {path}: {e}\n"
            "The file may be corrupted, password-protected, or not a valid "
            "Word document."
        ) from e
    return "\n".join(p.text for p in doc.paragraphs)


def read_pdf(path: str | Path) -> str:
    """Extract a text-based .pdf as Markdown (requires MarkItDown)."""
    if _get_markitdown() is None:
        raise ImportError(
            "markitdown is required to read .pdf files.\n"
            "Install it with:  pip install \"markitdown[docx,pdf]\""
        )
    converted = _convert_with_markitdown(Path(path))
    if converted is None:
        raise ValueError(
            f"Could not extract text from {path}.\n"
            "The PDF may be scanned (image-only), encrypted, or corrupted. "
            "Scanned PDFs are not supported offline — export the manuscript "
            "as .docx or a text-based PDF."
        )
    return converted


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
        # Auto-detect: prefer .tex, then .md, then .docx. PDFs are never
        # auto-picked: figure files share the .pdf extension.
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
    try:
        if suffix == ".tex":
            full_text = read_tex_recursive(main_file)
        elif suffix == ".docx":
            full_text = read_docx(main_file)
        elif suffix == ".pdf":
            full_text = read_pdf(main_file)
        else:
            full_text = read_file(main_file)
    except OSError as e:
        raise ValueError(f"Could not read manuscript {main_file}: {e}") from e

    # ---- Derive title ----
    title = _extract_title(full_text, suffix) or main_file.stem

    # ---- Find figures and tables alongside the manuscript ----
    base_dir = main_file.parent
    figure_exts = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg", ".tif", ".tiff"}
    figure_files = [
        str(p) for p in base_dir.iterdir()
        if p.suffix.lower() in figure_exts and p != main_file
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
    elif suffix in {".md", ".txt"}:
        # Markdown: first level-1 heading. Not for converted .docx/.pdf —
        # MarkItDown emits Word's Title style as plain text, so the first
        # "#" there is usually a section heading such as "Methods".
        m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    return ""
