# -*- mode: python ; coding: utf-8 -*-
# macOS build spec — produces ReviewPanel.app
# Sources live in ../src; the llmfit helper is downloaded next to this spec
# by build_mac.sh / CI (gitignored). SPECPATH = directory of this spec.

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SRC = os.path.abspath(os.path.join(SPECPATH, '..', 'src'))

a = Analysis(
    [os.path.join(SRC, 'gui.py')],
    pathex=[SRC],
    binaries=[
        # bundled hardware-check tool (darwin binary)
        (os.path.join(SPECPATH, 'llmfit'), '.'),
    ],
    datas=[
        # Destination MUST stay 'knowledge_base' — core.resource_path()
        # resolves sys._MEIPASS/knowledge_base at runtime.
        (os.path.join(SRC, 'knowledge_base'), 'knowledge_base'),
    ]
    # MarkItDown (.docx/.pdf -> Markdown): pdfminer ships CMap tables and
    # magika (imported by markitdown) ships its model config as data files.
    + collect_data_files('pdfminer')
    + collect_data_files('magika'),
    hiddenimports=[
        'customtkinter',
        'PIL',
        'PIL._tkinter_finder',
        'mammoth',
    ] + collect_submodules('markitdown.converters'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy ML stacks that leak in from a dev machine's global
        # site-packages via onnxruntime's optional submodules (magika needs
        # only onnxruntime's core inference session). Keeps the exe small.
        'torch', 'torchvision', 'torchaudio', 'tensorflow', 'keras',
        'transformers', 'accelerate', 'sympy',
        'onnxruntime.transformers', 'onnxruntime.tools',
        'onnxruntime.quantization', 'onnxruntime.training',
        # Optional deps of MarkItDown converters we never call (xlsx, etc.).
        'pandas', 'pyarrow', 'scipy', 'matplotlib', 'IPython',
    ],
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
        # Version source: src/core.py::__version__ — update together when bumping.
        'CFBundleShortVersionString': '2.2.1',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,   # allows dark mode
    },
)
