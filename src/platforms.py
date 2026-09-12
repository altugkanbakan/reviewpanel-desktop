"""
platforms.py — Single platform-abstraction layer for Review Panel.

Every OS-specific difference between the former windows/ and unix/ GUI
copies lives here, so gui.py can stay one file with only a handful of
`if IS_WINDOWS / IS_MAC` branches (the Ollama installer flows).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# subprocess.CREATE_NO_WINDOW keeps helper processes from flashing a
# console window on Windows; it does not exist on other platforms.
NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0

# ---------------------------------------------------------------------------
# Ollama download / install hints
# ---------------------------------------------------------------------------

OLLAMA_DOWNLOAD_PAGE = "https://ollama.com/download"
OLLAMA_WIN_URL = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_MAC_URL = "https://ollama.com/download/Ollama-darwin.zip"
OLLAMA_LINUX_CMD = "curl -fsSL https://ollama.com/install.sh | sh"


def ollama_install_hint() -> dict:
    """
    Platform-appropriate Ollama install info for the install dialog:
    {"desc": <user-facing text>, "button": <install-button label>,
     "url": <download url or None>, "cmd": <shell command or None>}
    """
    if IS_WINDOWS:
        return {
            "desc": "Ollama is required to run local AI models.\n"
                    "Click below to download and install it automatically.",
            "button": "Download & Install Ollama",
            "url": OLLAMA_WIN_URL,
            "cmd": None,
        }
    if IS_MAC:
        return {
            "desc": "Click below to download and install the Ollama Mac app "
                    "automatically.",
            "button": "Download & Install Ollama",
            "url": OLLAMA_MAC_URL,
            "cmd": None,
        }
    return {
        "desc": "Click 'Install Automatically' to run the official install "
                "script,\nor copy the command below and run it in your "
                "terminal.",
        "button": "Install Automatically",
        "url": None,
        "cmd": OLLAMA_LINUX_CMD,
    }


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

def mono_font_family() -> str:
    """Monospace family for the log textbox / command snippets."""
    return "Consolas" if IS_WINDOWS else "Courier"


# ---------------------------------------------------------------------------
# llmfit helper binary
# ---------------------------------------------------------------------------

def llmfit_binary_name() -> str:
    return "llmfit.exe" if IS_WINDOWS else "llmfit"


# ---------------------------------------------------------------------------
# Opening files with the OS default application
# ---------------------------------------------------------------------------

def open_path(path: str) -> None:
    """Open a file or folder with the platform's default handler."""
    if IS_WINDOWS:
        os.startfile(path)  # noqa: attribute exists on Windows only
    elif IS_MAC:
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ---------------------------------------------------------------------------
# User-level cache directory
# ---------------------------------------------------------------------------

def cache_dir() -> Path:
    """
    Per-user root for the persistent agent-output cache. Lives at the
    platform's conventional cache location — never next to the manuscript —
    so a review still hits the cache after the manuscript file is moved,
    and manuscript folders stay clean.
    """
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / "ReviewPanel" / "cache"
    if IS_MAC:
        return Path.home() / "Library" / "Caches" / "ReviewPanel"
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "reviewpanel"
