# Review Panel

AI-powered medical manuscript reviewer with automated hardware detection, Ollama integration, and a modern GUI.

Runs 6 sequential review agents locally via Ollama — no cloud, no data leaves your machine.

---

## Platforms

| Platform | Folder | Output |
|----------|--------|--------|
| Windows  | `windows/` | `ReviewPanel.exe` (Inno Setup installer) |
| macOS    | `unix/` | `ReviewPanel.app` + optional `.dmg` |
| Linux    | `unix/` | `ReviewPanel` binary |

---

## Windows — Build

Requirements: Python 3.10+, pip

```bat
cd windows
build.bat
```

The installer is created at `windows/dist/ReviewPanel_Setup.exe`.

---

## macOS — Build

```bash
cd unix
bash build_mac.sh
```

Output: `unix/dist/ReviewPanel.app`
Optional DMG requires `brew install create-dmg`.

---

## Linux — Build

```bash
cd unix
bash build_linux.sh
```

Output: `unix/dist/ReviewPanel`
To install system-wide: `sudo cp dist/ReviewPanel /usr/local/bin/reviewpanel`

---

## Automated Builds (GitHub Actions)

Push to `main` → GitHub Actions builds Mac + Linux binaries automatically.
See `.github/workflows/build.yml` for details.

Windows builds are done locally via `windows/build.bat`.

---

## Requirements

- [Ollama](https://ollama.com) (auto-installed on first run)
- A supported LLM model (app guides you through selection based on your hardware)

---

## License

AGPL v3 for open-source use. Commercial license available for proprietary/specialty deployments.
See [LICENSE](LICENSE) for details.

**Developer:** Altuğ Kanbakan — [GitHub](https://github.com/altugkanbakan) · [LinkedIn](https://linkedin.com/in/drkanbakan)
