# -*- mode: python ; coding: utf-8 -*-
# macOS build spec — produces ReviewPanel.app

a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[
        ('llmfit', '.'),   # bundled hardware-check tool (darwin binary)
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
    [],
    exclude_binaries=True,
    name='ReviewPanel',
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='ReviewPanel',
)

app = BUNDLE(
    coll,
    name='ReviewPanel.app',
    bundle_identifier='com.altugkanbakan.reviewpanel',
    info_plist={
        'CFBundleDisplayName': 'Review Panel',
        'CFBundleShortVersionString': '2.0',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,   # allows dark mode
    },
)
