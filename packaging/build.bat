@echo off
rem MeWallpaper 一键打包：PyInstaller -> Inno Setup
rem 前置：pip install pyinstaller；安装 Inno Setup 6（含 ISCC）
setlocal
cd /d "%~dp0\.."

where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo [1/3] 安装 PyInstaller...
    python -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo [1/3] PyInstaller 打包...
python -m PyInstaller packaging\MeWallpaper.spec --noconfirm || exit /b 1

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo 未找到 Inno Setup，请先安装 https://jrsoftware.org/isinfo.php
    exit /b 1
)

echo [2/3] Inno Setup 生成安装包...
"%ISCC%" packaging\setup.iss || exit /b 1

echo [3/3] 完成：packaging\output\
dir /b packaging\output
