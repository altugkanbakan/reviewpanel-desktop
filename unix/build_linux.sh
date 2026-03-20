#!/usr/bin/env bash
# build_linux.sh — Build ReviewPanel binary for Linux (x86_64)
# Run from the ReviewPanel-Unix directory on a Linux machine.
set -e

LLMFIT_VER="v0.8.0"
ARCH=$(uname -m)

echo "======================================================"
echo "  Review Panel — Linux build"
echo "  Architecture : $ARCH"
echo "======================================================"
echo ""

# 1. Download llmfit
if [ "$ARCH" = "aarch64" ]; then
    LLMFIT_ASSET="llmfit-${LLMFIT_VER}-aarch64-unknown-linux-gnu.tar.gz"
else
    LLMFIT_ASSET="llmfit-${LLMFIT_VER}-x86_64-unknown-linux-gnu.tar.gz"
fi
LLMFIT_URL="https://github.com/AlexsJones/llmfit/releases/download/${LLMFIT_VER}/${LLMFIT_ASSET}"

if [ ! -f "llmfit" ]; then
    echo "[1/3] Downloading llmfit ($ARCH)…"
    curl -L "$LLMFIT_URL" -o llmfit_tmp.tar.gz
    tar -xzf llmfit_tmp.tar.gz --strip-components=1
    chmod +x llmfit
    rm -f llmfit_tmp.tar.gz
    echo "      llmfit ready."
else
    echo "[1/3] llmfit already present — skipping download."
fi
echo ""

# 2. Python dependencies
echo "[2/3] Installing Python dependencies…"
pip install -r requirements.txt --quiet
echo ""

# 3. PyInstaller build
echo "[3/3] Building binary…"
pyinstaller ReviewPanel_linux.spec --noconfirm
echo ""

echo "======================================================"
echo "  Build complete!  Binary → dist/ReviewPanel"
echo ""
echo "  To make it available system-wide:"
echo "    sudo cp dist/ReviewPanel /usr/local/bin/reviewpanel"
echo "======================================================"
