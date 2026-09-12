# -*- mode: python ; coding: utf-8 -*-
# Linux build spec — produces a single ReviewPanel binary
# Sources live in ../src; the llmfit helper is downloaded next to this spec
# by build_linux.sh / CI (gitignored). SPECPATH = directory of this spec.

import os

SRC = os.path.abspath(os.path.join(SPECPATH, '..', 'src'))

a = Analysis(
    [os.path.join(SRC, 'gui.py')],
    pathex=[SRC],
    binaries=[
        # bundled hardware-check tool (linux binary)
        (os.path.join(SPECPATH, 'llmfit'), '.'),
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
)
