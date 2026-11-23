# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：MeWallpaper 打包为单目录 exe。

构建（在项目根目录执行）：
    pyinstaller packaging/MeWallpaper.spec --noconfirm
"""
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "app" / "players" / "libmpv-2.dll"), "app/players"),
        (str(ROOT / "app" / "icon.ico"), "app"),
        (str(ROOT / "web"), "web"),
    ],
    hiddenimports=[
        "mpv",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtNetwork",
        "webview",
        "flask",
        "PIL.Image",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "numpy", "pandas", "matplotlib"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MeWallpaper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=str(ROOT / "web" / "assets" / "logo.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MeWallpaper",
)
