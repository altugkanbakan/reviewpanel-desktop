#!/usr/bin/env bash
# build_mac.sh — Build ReviewPanel.app for macOS
# Run from the ReviewPanel-Unix directory on a Mac.
set -e

LLMFIT_VER="v0.8.0"
ARCH=$(uname -m)   # arm64 or x86_64

echo "======================================================"
echo "  Review Panel — macOS build"
echo "  Architecture : $ARCH"
echo "======================================================"
echo ""

# 1. Download the correct llmfit binary
if [ "$ARCH" = "arm64" ]; then
    LLMFIT_ASSET="llmfit-${LLMFIT_VER}-aarch64-apple-darwin.tar.gz"
else
    LLMFIT_ASSET="llmfit-${LLMFIT_VER}-x86_64-apple-darwin.tar.gz"
fi
LLMFIT_URL="https://github.com/AlexsJones/llmfit/releases/download/${LLMFIT_VER}/${LLMFIT_ASSET}"

if [ ! -f "llmfit" ]; then
    echo "[1/4] Downloading llmfit ($ARCH)…"
    curl -L "$LLMFIT_URL" -o llmfit_tmp.tar.gz
    tar -xzf llmfit_tmp.tar.gz --strip-components=1
    chmod +x llmfit
    rm -f llmfit_tmp.tar.gz
    echo "      llmfit ready."
else
    echo "[1/4] llmfit already present — skipping download."
fi
echo ""

# 2. Python dependencies
echo "[2/4] Installing Python dependencies…"
pip install -r requirements.txt --quiet
echo ""

# 3. PyInstaller build
echo "[3/4] Building .app bundle…"
pyinstaller ReviewPanel_mac.spec --noconfirm
echo ""

# 4. Optional: create a DMG
echo "[4/4] DMG packaging (optional)…"
if command -v create-dmg &> /dev/null; then
    create-dmg \
        --volname "Review Panel" \
        --window-size 540 380 \
        --icon-size 128 \
        --app-drop-link 380 190 \
        "dist/ReviewPanel.dmg" \
        "dist/ReviewPanel.app"
    echo "      DMG created → dist/ReviewPanel.dmg"
else
    echo "      create-dmg not found — skipping DMG."
    echo "      Install with: brew install create-dmg"
    echo "      App bundle is at: dist/ReviewPanel.app"
fi

echo ""
echo "======================================================"
echo "  Build complete!"
echo "======================================================"
