@echo off
rem MeWallpaper 一键打包：PyInstaller -> Inno Setup
rem 前置：pip install pyinstaller；安装 Inno Setup 6（含 ISCC）
setlocal
cd /d "%~dp0\.."

python -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo [0/3] 安装 PyInstaller...
    python -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo [0/3] 准备 mpv...
python packaging\fetch_mpv.py || exit /b 1

echo [1/3] PyInstaller 打包...
python -m PyInstaller packaging\MeWallpaper.spec --noconfirm || exit /b 1

rem PyInstaller 会按 PATH 顺序解析依赖 DLL：PATH 上其它软件（如 Git）的
rem libssl/libcrypto 可能抢先被打包，导致冻结版 _ssl 加载失败（webview 导入连锁失败）。
rem 打包后强制用当前 Python 运行时的原版 OpenSSL 覆盖。
for /f "usebackq delims=" %%D in (`python -c "import sys,pathlib;b=pathlib.Path(sys.base_prefix);d=b/'DLLs';print(d if (d/'libssl-3-x64.dll').exists() else b)"`) do set "PYDLLS=%%D"
if exist "%PYDLLS%\libssl-3-x64.dll" (
    copy /Y "%PYDLLS%\libssl-3-x64.dll" dist\MeWallpaper\_internal\ >nul
    copy /Y "%PYDLLS%\libcrypto-3-x64.dll" dist\MeWallpaper\_internal\ >nul
    echo 已用 Python 运行时原版 OpenSSL 覆盖: %PYDLLS%
)

set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
if not exist "%ISCC%" set "ISCC=D:\Program Files\Inno Setup 7\ISCC.exe"
if not exist "%ISCC%" set "ISCC=D:\Program Files\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo 未找到 Inno Setup，请先安装 https://jrsoftware.org/isinfo.php
    exit /b 1
)

echo [2/3] Inno Setup 生成安装包...
"%ISCC%" packaging\setup.iss || exit /b 1

echo [3/3] 完成：packaging\output\
dir /b packaging\output
