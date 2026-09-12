"""
Shared pytest configuration for the ReviewPanel test suite.

src/ is NOT a package (the GUI/PyInstaller entry points import the modules
as top-level names: `import core`, `from core import KB_BASE`, ...). We
mirror that exact import style here by prepending src/ to sys.path from
conftest.py instead of using a root-level `pytest.ini`/`pyproject.toml`
with `pythonpath = src`:

  * it keeps all test plumbing inside tests/ (no new root config file),
  * it needs no pytest ini-option support and works with any runner that
    imports conftest (pytest, IDEs, plain `python -m pytest`),
  * the path manipulation is explicit and greppable right where the
    tests live.

IMPORTANT: no test in this suite may import gui.py — it requires
customtkinter + a Tk display and breaks on headless CI.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

import core  # noqa: E402
import platforms  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """
    Repoint the persistent agent-output cache to a per-test temp folder
    for EVERY test (autouse), so the suite can never read from or write
    to the developer's real user-level cache directory.

    core.py imports cache_dir into its own namespace
    (`from platforms import cache_dir`), so both bindings are patched.
    Returns the temp cache root for tests that need to inspect it.
    """
    root = tmp_path / "reviewpanel_cache"
    monkeypatch.setattr(platforms, "cache_dir", lambda: root)
    monkeypatch.setattr(core, "cache_dir", lambda: root)
    return root


@pytest.fixture
def manuscript_data():
    """Minimal manuscript dict as produced by manuscript.discover_manuscript."""
    return {
        "title": "Test Manuscript",
        "full_text": "# Test Manuscript\n\nBackground. Methods. Results.",
        "figure_files": [],
        "table_files": [],
        "source_path": "C:/fake/manuscript.md",
    }


@pytest.fixture
def kb():
    """Small in-memory knowledge base (no disk access, no real KB files)."""
    return {
        "ama_style": "AMA style rules body",
        "patient_first": "term,replacement\ndiabetic,person with diabetes",
        "strobe": "STROBE checklist body",
        "consort": "CONSORT checklist body",
        "sampl": "SAMPL guidance body",
    }
