# -*- mode: python ; coding: utf-8 -*-
# Windows build spec — produces dist/ReviewPanel.exe (onefile)
# Sources live in ../src; the llmfit.exe helper is downloaded next to this
# spec by build.bat (gitignored). SPECPATH is provided by PyInstaller and is
# the directory containing this spec, so the build works from any CWD.

import os

SRC = os.path.abspath(os.path.join(SPECPATH, '..', 'src'))

a = Analysis(
    [os.path.join(SRC, 'gui.py')],
    pathex=[SRC],
    binaries=[
        # bundled hardware-check tool (windows binary)
        (os.path.join(SPECPATH, 'llmfit.exe'), '.'),
    ],
    datas=[
        # Destination MUST stay 'knowledge_base' — core.resource_path()
        # resolves sys._MEIPASS/knowledge_base at runtime.
        (os.path.join(SRC, 'knowledge_base'), 'knowledge_base'),
    ],
    hiddenimports=[
        'customtkinter',
        'PIL',
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ReviewPanel',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX never actually ran: PyInstaller disables it on non-Windows,
    # and the Windows runner has no upx binary — the v2.1.2 build log
    # shows no compression step. Left off deliberately; a packed,
    # unsigned exe is a common antivirus false positive and the
    # installer already uses lzma2 solid compression.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
