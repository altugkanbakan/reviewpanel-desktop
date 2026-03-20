"""
gui.py — Modern CustomTkinter GUI for Review Panel  (macOS / Linux)
Entry point: run this file or the compiled ReviewPanel binary / .app
"""

from __future__ import annotations

import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from agents import build_prompt, load_knowledge_base, run_agent
from core import KNOWN_JOURNALS, KB_BASE, build_report, load_journal_profile
from manuscript import discover_manuscript

# ---------------------------------------------------------------------------
# Theme & constants
# ---------------------------------------------------------------------------

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACCENT  = "#3B8ED0"
SUCCESS = "#4CAF50"
WARNING = "#FFA726"
ERROR   = "#EF5350"

IS_MAC   = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

_AGENT_NAMES = {
    1: "Medical Style & Grammar",
    2: "Internal Consistency & PICO",
    3: "Clinical Claims & Causality",
    4: "Biostatistics & Methodology",
    5: "Tables, Figures & Docs",
    6: "Clinical Impact & Referee",
}

_AGENT_QUIPS = {
    0: ["Loading manuscript…", "Reading your work…", "Parsing text…"],
    1: ["Polishing prose…", "Hunting stigmatizing language…", "Checking AMA style…"],
    2: ["Cross-referencing abstract vs. main text…", "Verifying PICO consistency…", "Tracing sample attrition…"],
    3: ["Sniffing out causal language…", "Separating association from causation…", "Flagging missing confounders…"],
    4: ["Crunching p-values…", "Verifying 95% confidence intervals…", "Applying SAMPL guidelines…"],
    5: ["Inspecting Table 1…", "Checking figure labels…", "Looking for missing legends…"],
    6: ["Channeling a demanding associate editor…", "Weighing clinical impact…", "Desk reject or not?…"],
}

# ---------------------------------------------------------------------------
# Helpers — llmfit
# ---------------------------------------------------------------------------

def _llmfit_bin() -> Path:
    """Return the path to the llmfit binary, checking multiple locations."""
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys._MEIPASS) / "llmfit")
        candidates.append(Path(sys.executable).parent / "llmfit")
    else:
        candidates.append(Path(__file__).parent / "llmfit")
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def run_llmfit() -> dict:
    exe = _llmfit_bin()
    if not exe.exists():
        return {"models": [], "error": f"llmfit not found at {exe}"}
    try:
        result = subprocess.run(
            [str(exe), "recommend", "--json", "--use-case", "reasoning", "--no-dashboard"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        return {"models": data.get("models", []), "error": None}
    except subprocess.TimeoutExpired:
        return {"models": [], "error": "llmfit timed out."}
    except Exception as exc:
        return {"models": [], "error": str(exc)}


def _fit_badge(fit_level: str) -> str:
    return {"Perfect": "✦ Perfect", "Good": "✔ Good", "Marginal": "~ Marginal"}.get(fit_level, fit_level)


def _model_label(m: dict) -> str:
    name  = m.get("name", "?")
    fit   = _fit_badge(m.get("fit_level", ""))
    tps   = m.get("estimated_tps", 0)
    ram   = m.get("memory_required_gb", 0)
    quant = m.get("best_quant", "")
    return f"{name}  [{fit} | {ram:.1f}GB | ~{tps:.0f}tok/s | {quant}]"


# ---------------------------------------------------------------------------
# Helpers — Ollama
# ---------------------------------------------------------------------------

def _ollama_installed() -> bool:
    return shutil.which("ollama") is not None


def _ollama_running() -> bool:
    try:
        import ollama
        ollama.list()
        return True
    except Exception:
        return False


def _ollama_models() -> list[str]:
    try:
        import ollama
        data = ollama.list()
        return [m["model"] for m in data.get("models", [])]
    except Exception:
        return []


def _ensure_ollama_serve(log_fn) -> bool:
    if _ollama_running():
        return True
    log_fn("  Ollama not responding — attempting to start it…")
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        log_fn("  [ERROR] 'ollama' not found on PATH.")
        return False
    for i in range(1, 16):
        time.sleep(1)
        if _ollama_running():
            log_fn(f"  Ollama started ({i}s).")
            return True
        log_fn(f"  Waiting for Ollama… {i}/15s")
    return False


# ---------------------------------------------------------------------------
# Hardware check window
# ---------------------------------------------------------------------------

class HardwareCheckWindow(ctk.CTkToplevel):
    def __init__(self, parent, on_model_selected):
        super().__init__(parent)
        self.title("Hardware Compatibility Check")
        self.geometry("720x520")
        self.resizable(False, False)
        self.grab_set()

        self._on_model_selected = on_model_selected
        self._model_map: dict[str, str] = {}

        self._build_ui()
        threading.Thread(target=self._run_check, daemon=True).start()

    def _build_ui(self):
        ctk.CTkLabel(
            self, text="Hardware Compatibility Check",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(pady=(20, 4))
        ctk.CTkLabel(
            self,
            text="Analyzing your GPU / CPU to find models that fit your machine…",
            text_color="gray",
        ).pack(pady=(0, 16))

        self._spinner = ctk.CTkProgressBar(self, mode="indeterminate", width=400)
        self._spinner.pack(pady=(0, 16))
        self._spinner.start()

        self._status = ctk.CTkLabel(self, text="Running llmfit…", text_color="gray")
        self._status.pack()

        self._result_frame = ctk.CTkScrollableFrame(self, width=660, height=240)
        self._result_frame.pack(padx=20, pady=12, fill="both", expand=True)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 16))

        self._use_btn = ctk.CTkButton(
            btn_row, text="Use Selected Model", state="disabled",
            command=self._use_selected,
        )
        self._use_btn.pack(side="right", padx=(8, 0))

        self._pull_btn = ctk.CTkButton(
            btn_row, text="⬇ Pull Model", state="disabled",
            fg_color="gray35", hover_color="gray45",
            command=self._pull_selected,
        )
        self._pull_btn.pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_row, text="Close", fg_color="gray40",
            command=self.destroy,
        ).pack(side="right")

    def _run_check(self):
        data = run_llmfit()
        self.after(0, lambda: self._show_results(data))

    def _show_results(self, data: dict):
        self._spinner.stop()
        self._spinner.pack_forget()

        models = data.get("models", [])
        err    = data.get("error")

        if err and not models:
            self._status.configure(
                text=f"⚠  Could not run hardware check: {err}", text_color=WARNING,
            )
            return

        usable = [m for m in models if m.get("fit_level") in ("Perfect", "Good", "Marginal")]
        if not usable:
            self._status.configure(
                text="✗  No compatible models found.\nOllama is not recommended for this machine.",
                text_color=ERROR,
            )
            return

        perfect = [m for m in usable if m["fit_level"] == "Perfect"]
        good    = [m for m in usable if m["fit_level"] == "Good"]
        marg    = [m for m in usable if m["fit_level"] == "Marginal"]

        self._status.configure(
            text=f"✔  {len(perfect)} perfect, {len(good)} good, {len(marg)} marginal fits.",
            text_color=SUCCESS,
        )

        self._radio_var = ctk.StringVar(value="")
        for section, items, color in [
            ("✦ Perfect Fit", perfect, SUCCESS),
            ("✔ Good Fit",    good,    ACCENT),
            ("~ Marginal",    marg,    WARNING),
        ]:
            if not items:
                continue
            ctk.CTkLabel(
                self._result_frame, text=section,
                font=ctk.CTkFont(weight="bold"), text_color=color,
            ).pack(anchor="w", padx=8, pady=(10, 2))
            for m in items[:8]:
                label = _model_label(m)
                self._model_map[label] = m["name"]
                ctk.CTkRadioButton(
                    self._result_frame, text=label,
                    variable=self._radio_var, value=label,
                    command=self._on_radio_select,
                    font=ctk.CTkFont(size=12),
                ).pack(anchor="w", padx=16, pady=2)

    def _on_radio_select(self):
        self._use_btn.configure(state="normal")
        self._pull_btn.configure(state="normal")

    def _pull_selected(self):
        label = self._radio_var.get()
        if not label or label not in self._model_map:
            return
        model = self._model_map[label]
        if not _ollama_installed():
            OllamaInstallDialog(self, on_done=lambda: ModelPullDialog(self, model, on_done=self._on_pull_done))
            return
        ModelPullDialog(self, model, on_done=self._on_pull_done)

    def _on_pull_done(self, model: str):
        self._on_model_selected(model)
        self.destroy()

    def _use_selected(self):
        label = self._radio_var.get()
        if label and label in self._model_map:
            self._on_model_selected(self._model_map[label])
        self.destroy()


# ---------------------------------------------------------------------------
# Ollama install dialog  — macOS / Linux aware
# ---------------------------------------------------------------------------

class OllamaInstallDialog(ctk.CTkToplevel):
    _MAC_URL   = "https://ollama.com/download/Ollama-darwin.zip"
    _LINUX_CMD = "curl -fsSL https://ollama.com/install.sh | sh"

    def __init__(self, parent, on_done):
        super().__init__(parent)
        self.title("Install Ollama")
        self.geometry("500x300")
        self.resizable(False, False)
        self.grab_set()
        self._on_done = on_done
        self._build_ui()

    def _build_ui(self):
        ctk.CTkLabel(
            self, text="Ollama Not Found",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(pady=(20, 6))

        if IS_MAC:
            desc = "Click below to download and install the Ollama Mac app automatically."
        else:
            desc = (
                "Click 'Install Automatically' to run the official install script,\n"
                "or copy the command below and run it in your terminal."
            )
        ctk.CTkLabel(self, text=desc, wraplength=440).pack(pady=(0, 12))

        if IS_LINUX:
            cmd_frame = ctk.CTkFrame(self, fg_color="gray20", corner_radius=8)
            cmd_frame.pack(fill="x", padx=24, pady=(0, 12))
            ctk.CTkLabel(
                cmd_frame, text=self._LINUX_CMD,
                font=ctk.CTkFont(family="Courier", size=11),
                text_color="lightgreen",
            ).pack(padx=12, pady=8)

        self._bar = ctk.CTkProgressBar(self, width=440)
        self._bar.set(0)
        self._bar.pack(pady=(0, 6))

        self._status = ctk.CTkLabel(self, text="", text_color="gray")
        self._status.pack()

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=14)

        self._install_btn = ctk.CTkButton(
            btn_row,
            text="Download & Install Ollama" if IS_MAC else "Install Automatically",
            command=self._start_install,
        )
        self._install_btn.pack(side="left", padx=6)

        ctk.CTkButton(
            btn_row, text="Open Download Page",
            fg_color="gray30", hover_color="gray40",
            command=lambda: webbrowser.open("https://ollama.com/download"),
        ).pack(side="left", padx=6)

    def _start_install(self):
        self._install_btn.configure(state="disabled")
        self._bar.configure(mode="indeterminate")
        self._bar.start()
        if IS_MAC:
            self._status.configure(text="Downloading Ollama…")
            threading.Thread(target=self._install_mac, daemon=True).start()
        else:
            self._status.configure(text="Running install script (may need password)…")
            threading.Thread(target=self._install_linux, daemon=True).start()

    # ---- macOS: download zip, extract to /Applications ----
    def _install_mac(self):
        import urllib.request, tempfile
        try:
            tmp_zip = tempfile.mktemp(suffix=".zip")
            urllib.request.urlretrieve(self._MAC_URL, tmp_zip)
            self.after(0, lambda: self._status.configure(text="Extracting…"))

            tmp_dir = tempfile.mkdtemp()
            with zipfile.ZipFile(tmp_zip, "r") as z:
                z.extractall(tmp_dir)
            os.unlink(tmp_zip)

            # Find the .app inside the extracted dir
            apps = list(Path(tmp_dir).glob("**/*.app"))
            if not apps:
                raise FileNotFoundError("Ollama.app not found in downloaded zip.")

            dest = Path("/Applications") / apps[0].name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(apps[0]), str(dest))

            # Launch Ollama
            subprocess.Popen(["open", str(dest)])
            self.after(0, self._install_done)
        except Exception as exc:
            self.after(0, lambda: self._finish_err(str(exc)))

    # ---- Linux: run install.sh via pkexec or bare sh ----
    def _install_linux(self):
        try:
            # Try graphical privilege escalation first (works on GNOME/KDE)
            result = subprocess.run(
                ["pkexec", "bash", "-c", self._LINUX_CMD],
                timeout=120,
            )
            if result.returncode == 0:
                self.after(0, self._install_done)
            else:
                raise RuntimeError(f"Install script exited with code {result.returncode}")
        except FileNotFoundError:
            # pkexec not available — try plain sh (works if already root)
            try:
                subprocess.run(["bash", "-c", self._LINUX_CMD], check=True, timeout=120)
                self.after(0, self._install_done)
            except Exception as exc:
                self.after(0, lambda: self._finish_err(
                    f"{exc}\n\nTry running manually in a terminal:\n{self._LINUX_CMD}"
                ))
        except Exception as exc:
            self.after(0, lambda: self._finish_err(str(exc)))

    def _install_done(self):
        self._bar.stop()
        self._bar.configure(mode="determinate")
        self._bar.set(1)
        self._status.configure(text="Ollama installed successfully!", text_color=SUCCESS)
        self.after(1500, lambda: [self.destroy(), self._on_done()])

    def _finish_err(self, msg: str):
        self._bar.stop()
        self._status.configure(text=f"Failed: {msg}", text_color=ERROR)
        self._install_btn.configure(state="normal")


# ---------------------------------------------------------------------------
# Model pull dialog
# ---------------------------------------------------------------------------

class ModelPullDialog(ctk.CTkToplevel):
    def __init__(self, parent, model: str, on_done=None):
        super().__init__(parent)
        self.title(f"Downloading — {model}")
        self.geometry("480x240")
        self.resizable(False, False)
        self.grab_set()

        self._model     = model
        self._on_done   = on_done
        self._cancelled = False

        self._build_ui()
        threading.Thread(target=self._do_pull, daemon=True).start()

    def _build_ui(self):
        ctk.CTkLabel(
            self, text=f"Pulling  {self._model}",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(pady=(24, 6))

        self._status = ctk.CTkLabel(self, text="Starting download…", text_color="gray")
        self._status.pack()

        self._bar = ctk.CTkProgressBar(self, width=420)
        self._bar.set(0)
        self._bar.pack(pady=16)

        self._detail = ctk.CTkLabel(self, text="", text_color="gray",
                                    font=ctk.CTkFont(size=11))
        self._detail.pack()

        self._cancel_btn = ctk.CTkButton(
            self, text="Cancel", width=120,
            fg_color="gray35", hover_color=ERROR,
            command=self._cancel,
        )
        self._cancel_btn.pack(pady=(16, 0))

    def _do_pull(self):
        try:
            import ollama
            for chunk in ollama.pull(self._model, stream=True):
                if self._cancelled:
                    return
                status    = chunk.get("status", "")
                total     = chunk.get("total", 0)
                completed = chunk.get("completed", 0)
                if total and completed:
                    frac     = completed / total
                    done_mb  = completed / 1_048_576
                    total_mb = total / 1_048_576
                    detail   = f"{done_mb:.1f} MB / {total_mb:.1f} MB"
                    self.after(0, lambda f=frac, d=detail, s=status: self._update(f, d, s))
                else:
                    self.after(0, lambda s=status: self._update(None, "", s))
            if not self._cancelled:
                self.after(0, self._finish_ok)
        except Exception as exc:
            if not self._cancelled:
                self.after(0, lambda: self._finish_err(str(exc)))

    def _update(self, frac, detail, status):
        self._status.configure(text=status or "Downloading…")
        if frac is not None:
            self._bar.configure(mode="determinate")
            self._bar.set(frac)
        else:
            self._bar.configure(mode="indeterminate")
            self._bar.start()
        self._detail.configure(text=detail)

    def _finish_ok(self):
        self._bar.configure(mode="determinate")
        self._bar.set(1)
        self._status.configure(text="✔  Download complete!", text_color=SUCCESS)
        self._detail.configure(text="")
        self._cancel_btn.configure(text="Close", fg_color=ACCENT,
                                   hover_color=ACCENT, command=self._close_ok)

    def _finish_err(self, msg: str):
        self._bar.stop()
        self._status.configure(text=f"✗  {msg}", text_color=ERROR)
        self._cancel_btn.configure(text="Close", fg_color="gray35", command=self.destroy)

    def _cancel(self):
        self._cancelled = True
        self.destroy()

    def _close_ok(self):
        self.destroy()
        if self._on_done:
            self._on_done(self._model)


# ---------------------------------------------------------------------------
# About window
# ---------------------------------------------------------------------------

class AboutWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("About Review Panel")
        self.geometry("400x320")
        self.resizable(False, False)
        self.grab_set()
        self._build_ui()

    def _build_ui(self):
        ctk.CTkLabel(
            self, text="✦ Review Panel",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=ACCENT,
        ).pack(pady=(28, 4))
        ctk.CTkLabel(
            self, text="Medical Manuscript Reviewer",
            font=ctk.CTkFont(size=13), text_color="gray",
        ).pack()

        ctk.CTkFrame(self, height=1, fg_color="gray30").pack(fill="x", padx=32, pady=20)

        ctk.CTkLabel(self, text="Developed by", text_color="gray",
                     font=ctk.CTkFont(size=12)).pack()
        ctk.CTkLabel(self, text="Altuğ Kanbakan",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(2, 16))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack()

        ctk.CTkButton(
            btn_frame, text="⌥  GitHub", width=150, height=36,
            fg_color="gray25", hover_color="gray35",
            command=lambda: webbrowser.open("https://github.com/altugkanbakan"),
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            btn_frame, text="in  LinkedIn", width=150, height=36,
            fg_color="#0A66C2", hover_color="#0856a0",
            command=lambda: webbrowser.open("https://www.linkedin.com/in/drkanbakan/"),
        ).pack(side="left", padx=6)

        ctk.CTkLabel(self, text="v2.0", text_color="gray40",
                     font=ctk.CTkFont(size=11)).pack(pady=(20, 0))


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class ReviewApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Review Panel — Medical Manuscript Reviewer")
        self.geometry("860x680")
        self.minsize(720, 580)

        self._log_queue: queue.Queue = queue.Queue()
        self._report_path: str | None = None
        self._ticker_running = False
        self._current_agent  = 0
        self._quip_index     = 0

        self._build_ui()
        self._poll_queue()
        threading.Thread(target=self._startup_checks, daemon=True).start()

    def _build_ui(self):
        # ---- Top bar ----
        topbar = ctk.CTkFrame(self, height=50, corner_radius=0)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)

        ctk.CTkLabel(
            topbar, text="  ✦ Review Panel",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=ACCENT,
        ).pack(side="left", padx=12)

        ctk.CTkButton(
            topbar, text="Hardware Check", width=140, height=30,
            fg_color="gray30", hover_color="gray40",
            command=self._open_hw_check,
        ).pack(side="right", padx=8, pady=8)

        ctk.CTkButton(
            topbar, text="ℹ  About", width=90, height=30,
            fg_color="gray30", hover_color="gray40",
            command=lambda: AboutWindow(self),
        ).pack(side="right", padx=(0, 4), pady=8)

        ctk.CTkButton(
            topbar, text="☀ Light / 🌙 Dark", width=140, height=30,
            fg_color="gray30", hover_color="gray40",
            command=self._toggle_theme,
        ).pack(side="right", padx=(0, 4), pady=8)

        # ---- Main content ----
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=16, pady=12)

        # Left column — settings
        left = ctk.CTkFrame(content, width=280, corner_radius=12)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        ctk.CTkLabel(left, text="Settings",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            pady=(16, 10), padx=16, anchor="w")

        ctk.CTkLabel(left, text="Manuscript file", text_color="gray").pack(anchor="w", padx=16)
        file_row = ctk.CTkFrame(left, fg_color="transparent")
        file_row.pack(fill="x", padx=16, pady=(2, 12))
        self._file_var = ctk.StringVar()
        ctk.CTkEntry(file_row, textvariable=self._file_var,
                     placeholder_text="No file selected").pack(
            side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(file_row, text="…", width=36, command=self._browse).pack(side="left")

        ctk.CTkLabel(left, text="Target journal", text_color="gray").pack(anchor="w", padx=16)
        self._journal_var = ctk.StringVar(value="top-medical")
        ctk.CTkComboBox(
            left, variable=self._journal_var,
            values=KNOWN_JOURNALS, state="readonly", width=248,
        ).pack(padx=16, pady=(2, 12))

        ctk.CTkLabel(left, text="Ollama model", text_color="gray").pack(anchor="w", padx=16)
        model_row = ctk.CTkFrame(left, fg_color="transparent")
        model_row.pack(fill="x", padx=16, pady=(2, 4))
        self._model_var = ctk.StringVar(value="qwen2.5:7b")
        self._model_combo = ctk.CTkComboBox(
            model_row, variable=self._model_var,
            values=self._build_model_list(), width=210,
        )
        self._model_combo.pack(side="left", padx=(0, 6))
        ctk.CTkButton(model_row, text="⟳", width=30,
                      command=self._refresh_models).pack(side="left")

        ctk.CTkButton(
            left, text="⬇  Pull Model", height=32,
            fg_color="gray30", hover_color="gray40",
            command=self._pull_current_model,
        ).pack(fill="x", padx=16, pady=(4, 0))

        self._hw_label = ctk.CTkLabel(
            left, text="", text_color="gray",
            font=ctk.CTkFont(size=11), wraplength=248,
        )
        self._hw_label.pack(anchor="w", padx=16, pady=(4, 16))

        ctk.CTkFrame(left, fg_color="transparent").pack(fill="y", expand=True)

        self._run_btn = ctk.CTkButton(
            left, text="▶  Run Review", height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._start,
        )
        self._run_btn.pack(fill="x", padx=16, pady=(0, 8))

        self._open_btn = ctk.CTkButton(
            left, text="📄  Open Report", height=36,
            fg_color="gray35", hover_color="gray45",
            state="disabled", command=self._open_report,
        )
        self._open_btn.pack(fill="x", padx=16, pady=(0, 16))

        # Right column — log + progress
        right = ctk.CTkFrame(content, corner_radius=12)
        right.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(right, text="Progress",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            pady=(16, 8), padx=16, anchor="w")

        agent_grid = ctk.CTkFrame(right, fg_color="transparent")
        agent_grid.pack(fill="x", padx=16, pady=(0, 10))
        self._agent_labels: dict[int, ctk.CTkLabel] = {}
        for i in range(1, 7):
            col  = (i - 1) % 3
            row  = (i - 1) // 3
            cell = ctk.CTkFrame(agent_grid, corner_radius=8, fg_color="gray25")
            cell.grid(row=row, column=col, padx=4, pady=4, sticky="ew")
            agent_grid.columnconfigure(col, weight=1)
            lbl = ctk.CTkLabel(
                cell, text=f"  {i}. {_AGENT_NAMES[i]}",
                font=ctk.CTkFont(size=11), text_color="gray50", anchor="w",
            )
            lbl.pack(fill="x", padx=6, pady=6)
            self._agent_labels[i] = lbl

        self._progress = ctk.CTkProgressBar(right, height=8)
        self._progress.set(0)
        self._progress.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(right, text="Log", text_color="gray").pack(anchor="w", padx=16)
        self._log = ctk.CTkTextbox(
            right, state="disabled", wrap="word",
            font=ctk.CTkFont(family="Courier", size=11),
        )
        self._log.pack(fill="both", expand=True, padx=16, pady=(4, 8))

        self._status_var = ctk.StringVar(value="Ready — select a manuscript and click Run.")
        ctk.CTkLabel(
            right, textvariable=self._status_var,
            text_color="gray", font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=16, pady=(0, 12))

    def _build_model_list(self) -> list[str]:
        pulled   = _ollama_models()
        defaults = ["qwen2.5:7b", "qwen2.5:3b", "llama3.2:3b",
                    "gemma3:4b", "llama3.1:8b", "mistral:7b", "qwen2.5:14b"]
        return pulled + [m for m in defaults if m not in pulled] or ["qwen2.5:7b"]

    def _refresh_models(self):
        values = self._build_model_list()
        self._model_combo.configure(values=values)
        self._hw_label.configure(text=f"Refreshed. {len(values)} model(s) available.")

    def _pull_current_model(self):
        model = self._model_var.get().strip()
        if not model:
            return
        if not _ollama_installed():
            OllamaInstallDialog(self, on_done=lambda: self._open_pull_dialog(model))
            return
        self._open_pull_dialog(model)

    def _open_pull_dialog(self, model: str):
        def on_done(m):
            self._refresh_models()
            self._model_var.set(m)
        ModelPullDialog(self, model, on_done=on_done)

    def _startup_checks(self):
        data    = run_llmfit()
        models  = data.get("models", [])
        perfect = [m for m in models if m["fit_level"] == "Perfect"]
        good    = [m for m in models if m["fit_level"] == "Good"]
        if not models:
            msg = "⚠ Hardware check unavailable."
        elif not perfect and not good:
            msg = "⚠ No well-fitting models for your hardware."
        else:
            msg = f"✔ {len(perfect)} perfect + {len(good)} good fits detected."
        self.after(0, lambda: self._hw_label.configure(text=msg))

    def _open_hw_check(self):
        HardwareCheckWindow(self, on_model_selected=self._apply_hw_model)

    def _apply_hw_model(self, model_name: str):
        self._model_var.set(model_name)
        if not _ollama_installed():
            OllamaInstallDialog(self, on_done=lambda: None)

    def _toggle_theme(self):
        ctk.set_appearance_mode(
            "light" if ctk.get_appearance_mode() == "Dark" else "dark"
        )

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select Manuscript",
            filetypes=[
                ("Supported files", "*.md *.tex *.docx *.txt"),
                ("Word Document", "*.docx"),
                ("Markdown", "*.md"),
                ("LaTeX", "*.tex"),
                ("Text", "*.txt"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._file_var.set(path)

    def _append_log(self, text: str):
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _set_agent_state(self, num: int, state: str):
        colors = {
            "waiting": ("gray25", "gray50"),
            "running": ("gray30", ACCENT),
            "done":    ("gray25", SUCCESS),
            "error":   ("gray25", ERROR),
        }
        bg, fg = colors.get(state, ("gray25", "gray50"))
        lbl = self._agent_labels.get(num)
        if lbl:
            lbl.configure(text_color=fg)
            lbl.master.configure(fg_color=bg)

    def _poll_queue(self):
        try:
            while True:
                msg  = self._log_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._append_log(msg[1])
                elif kind == "agent_start":
                    self._set_agent_state(msg[1], "running")
                elif kind == "agent_done":
                    self._set_agent_state(msg[1], "done")
                    self._progress.set(msg[1] / 6)
                elif kind == "agent_error":
                    self._set_agent_state(msg[1], "error")
                elif kind == "done":
                    self._report_path = msg[1]
                    self._on_finish(success=True)
                elif kind == "error":
                    self._on_finish(success=False, error=msg[1])
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _tick_status(self):
        if not self._ticker_running:
            return
        quips = _AGENT_QUIPS.get(self._current_agent, ["Working…"])
        quip  = quips[self._quip_index % len(quips)]
        label = f"Agent {self._current_agent}/6 — " if self._current_agent > 0 else ""
        self._status_var.set(f"{label}{quip}")
        self._quip_index += 1
        self.after(3000, self._tick_status)

    def _start(self):
        file_path = self._file_var.get().strip() or None
        journal   = self._journal_var.get()
        model     = self._model_var.get().strip() or "qwen2.5:7b"

        self._run_btn.configure(state="disabled")
        self._open_btn.configure(state="disabled")
        self._progress.set(0)
        self._report_path   = None
        self._current_agent = 0
        self._quip_index    = 0
        self._ticker_running = True
        self._tick_status()

        for i in range(1, 7):
            self._set_agent_state(i, "waiting")

        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

        threading.Thread(
            target=self._thread_run,
            args=(file_path, journal, model),
            daemon=True,
        ).start()

    def _thread_run(self, file_path: str | None, journal: str, model: str):
        q = self._log_queue

        def log(msg: str):
            q.put(("log", msg))

        try:
            log("=" * 54)
            log("  Review Panel — Medical Manuscript Reviewer")
            log("=" * 54)
            log(f"  Journal : {journal}")
            log(f"  Model   : {model}")
            log(f"  Platform: {platform.system()} {platform.machine()}")
            log("")

            log("[Phase 1] Loading manuscript …")
            manuscript_data = discover_manuscript(file_path)
            log(f"  Title      : {manuscript_data['title']}")
            log(f"  Source     : {manuscript_data['source_path']}")
            log(f"  Characters : {len(manuscript_data['full_text']):,}")

            journal_profile_text = load_journal_profile(journal, KB_BASE)
            log(f"  Journal profile: {journal if journal_profile_text else 'top-medical (default)'}")
            log("")

            log("[Phase 2] Checking Ollama connection …")
            if not _ensure_ollama_serve(log):
                q.put(("error",
                       "Could not connect to Ollama.\n\n"
                       "Make sure Ollama is installed and try again.\n"
                       "Download: https://ollama.com/download"))
                return
            log("  Connected. Running 6 agents sequentially …")
            log("  (Each agent may take 1–5 minutes depending on model/hardware)")
            log("")

            kb = load_knowledge_base()
            agent_outputs: list[str] = []
            review_start = time.time()

            for num in range(1, 7):
                self._current_agent = num
                q.put(("agent_start", num))
                log(f"[{num}/6] Agent {num}: {_AGENT_NAMES[num]} …")
                t0     = time.time()
                prompt = build_prompt(
                    num, manuscript_data["full_text"], kb,
                    journal_profile_text if num == 6 else "",
                )
                result  = run_agent(num, prompt, model=model, verbose=False)
                elapsed = time.time() - t0
                agent_outputs.append(result)
                q.put(("agent_done", num))
                log(f"[{num}/6] Done  ({len(result):,} chars, {elapsed:.0f}s)")
                log("")

            log("[Phase 3] Assembling report …")
            output_dir  = Path(manuscript_data["source_path"]).parent
            report_path = build_report(
                agent_outputs=agent_outputs,
                manuscript_data=manuscript_data,
                journal=journal,
                model=model,
                output_dir=output_dir,
            )
            total = time.time() - review_start
            mins, secs = divmod(int(total), 60)
            log(f"Report saved → {report_path}")
            log("")
            log("=" * 54)
            log(f"  Review complete!  Total time: {mins}m {secs}s")
            log("=" * 54)
            q.put(("done", str(report_path)))

        except Exception as exc:
            import traceback
            log(f"\n[ERROR] {exc}")
            log(traceback.format_exc())
            for i in range(self._current_agent, 7):
                q.put(("agent_error", i))
            q.put(("error", str(exc)))

    def _on_finish(self, success: bool, error: str = ""):
        self._ticker_running = False
        self._run_btn.configure(state="normal")
        if success:
            self._status_var.set("✔  Done!  Report saved next to your manuscript.")
            self._open_btn.configure(state="normal")
            self._progress.set(1)
        else:
            self._status_var.set("✗  Failed — see log for details.")
            messagebox.showerror("Review failed", error)

    def _open_report(self):
        if self._report_path:
            if IS_MAC:
                subprocess.Popen(["open", self._report_path])
            else:
                subprocess.Popen(["xdg-open", self._report_path])


def main():
    app = ReviewApp()
    app.mainloop()


if __name__ == "__main__":
    main()
