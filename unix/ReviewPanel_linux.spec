# -*- mode: python ; coding: utf-8 -*-
# Linux build spec — produces a single ReviewPanel binary

a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[
        ('llmfit', '.'),   # bundled hardware-check tool (linux binary)
    ],
    datas=[
        ('knowledge_base', 'knowledge_base'),
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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
)
