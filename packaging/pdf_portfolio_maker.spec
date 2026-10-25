# -*- mode: python ; coding: utf-8 -*-
"""
pdf_portfolio_maker.spec
------------------------
Optimized PyInstaller specification for PDF Portfolio Maker.
Target: Windows 64-bit (x64 / ARM64 compatible)
Mode:   --onedir (directory bundle for Inno Setup installer packaging)
"""

import sys
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None
project_root = os.path.abspath(os.path.join(SPECPATH, '..'))

# 1. Collect required submodules
hidden_imports = []
hidden_imports += collect_submodules('pypdf')
hidden_imports += collect_submodules('cryptography')
hidden_imports += collect_submodules('src')

# 2. Collect essential package data
datas = []
assets_dir = os.path.join(project_root, 'assets')
if os.path.exists(assets_dir):
    datas.append((assets_dir, 'assets'))

# 3. Explicit module exclusions to eliminate unused Qt frameworks & stdlib bloat
excluded_modules = [
    # Qt Heavyweight Modules (Saves ~200+ MB)
    'PySide6.QtWebEngine',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineQuick',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtQuickWidgets',
    'PySide6.QtQuickControls2',
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
    'PySide6.Qt3DCore',
    'PySide6.Qt3DRender',
    'PySide6.Qt3DInput',
    'PySide6.Qt3DLogic',
    'PySide6.Qt3DAnimation',
    'PySide6.Qt3DExtras',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'PySide6.QtSensors',
    'PySide6.QtPositioning',
    'PySide6.QtLocation',
    'PySide6.QtBluetooth',
    'PySide6.QtNfc',
    'PySide6.QtNetworkAuth',
    'PySide6.QtSql',
    'PySide6.QtTest',
    'PySide6.QtXml',
    'PySide6.QtSpatialAudio',
    'PySide6.QtDesigner',
    'PySide6.QtUiTools',
    
    # Python stdlib bloat
    'tkinter',
    'unittest',
    'test',
    'pydoc',
    'doctest',
]

a = Analysis(
    [os.path.join(project_root, 'app.py')],  # Target entry point
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 4. Strict Binary Filtering: Strip unwanted Qt dynamic libraries collected transitively
unwanted_binary_patterns = (
    'Qt6WebEngine',
    'Qt6Quick',
    'Qt6Qml',
    'Qt6Multimedia',
    'Qt63D',
    'Qt6Pdf',
    'Qt6Sensors',
    'Qt6Positioning',
    'Qt6Location',
    'Qt6Bluetooth',
    'Qt6Nfc',
    'Qt6Sql',
    'Qt6SpatialAudio',
    'd3dcompiler_47.dll',
)

a.binaries = [
    item for item in a.binaries
    if not any(pattern.lower() in item[0].lower() for pattern in unwanted_binary_patterns)
]

# 5. Data Filtering: Strip unused non-English Qt translation catalogs
a.datas = [
    item for item in a.datas
    if not (
        'translations' in item[0].lower()
        and not item[0].lower().endswith('qtbase_en.qm')
    )
]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PDFPortfolioMaker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX disabled to avoid AV heuristic false positives
    console=False,  # Windowed GUI application (no cmd prompt)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(project_root, 'assets', 'app_icon.ico') if os.path.exists(os.path.join(project_root, 'assets', 'app_icon.ico')) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PDFPortfolioMaker',
)
