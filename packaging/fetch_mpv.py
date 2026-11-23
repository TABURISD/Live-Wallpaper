# -*- coding: utf-8 -*-
"""下载 mpv 官方 Windows 完整构建并提取 mpv.exe 到 app/players/。

mpv.exe 体积约 100 MB，超出 GitHub 单文件 100 MB 限制，不入库；
构建前由本脚本自动获取（GitHub 直连，失败时走公开加速镜像）。

来源：shinchiro/mpv-winbuild-cmake（mpv 官方 Windows 构建）
许可证：见 licenses/THIRD-PARTY-LICENSES.md
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE_DIR = ROOT / "app" / "players"
EXE = EXE_DIR / "mpv.exe"

RELEASE = "20261111"
ASSET = f"mpv-x86_64-{RELEASE}-git-bcde6b93cc.7z"
GH_URL = (
    "https://github.com/shinchiro/mpv-winbuild-cmake/releases/"
    f"download/{RELEASE}/{ASSET}"
)
MIRRORS = [
    "https://ghfast.top/" + GH_URL,
    "https://gh-proxy.com/" + GH_URL,
    GH_URL,
]

# 官方完整包 7z 实测约 34 MB（高压缩），mpv.exe 提取后约 90 MB
MIN_SIZE = 30 * 1024 * 1024


def log(msg: str) -> None:
    print(f"[fetch-mpv] {msg}", flush=True)


def download(url: str, dest: Path) -> bool:
    log(f"下载 {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MeWallpaper-build"})
        with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f, 1024 * 256)
    except Exception as e:  # noqa: BLE001
        log(f"失败: {e}")
        return False
    return True


def extract_exe(archive: Path, dest: Path) -> bool:
    """解包并取出 mpv.exe。

    官方包用 BCJ2 过滤器压缩，py7zr 不支持；改用 7-Zip 官方独立版
    7zr.exe（www.7-zip.org 直接下载，无需安装）。
    """
    import shutil as _sh
    import subprocess as _sp
    import urllib.request as _ur

    zr = archive.parent / "7zr.exe"
    if not zr.exists():
        url = "https://www.7-zip.org/a/7zr.exe"
        log(f"下载 7zr.exe ({url})")
        req = _ur.Request(url, headers={"User-Agent": "MeWallpaper-build"})
        with _ur.urlopen(req, timeout=30) as r, open(zr, "wb") as f:
            _sh.copyfileobj(r, f)
    outdir = archive.parent / "_x"
    outdir.mkdir(exist_ok=True)
    r = _sp.run([str(zr), "x", "-y", f"-o{outdir}", str(archive)],
                capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        log(f"7zr 解包失败: {r.stdout[-300:]} {r.stderr[-300:]}")
        return False
    found = list(outdir.rglob("mpv.exe"))
    if not found:
        return False
    _sh.move(str(found[0]), str(dest))
    return True


def main() -> int:
    if EXE.exists() and EXE.stat().st_size >= MIN_SIZE:
        log(f"已存在，跳过: {EXE}")
        return 0
    EXE_DIR.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="mpv-"))
    archive = tmpdir / ASSET
    try:
        for url in MIRRORS:
            if download(url, archive) and archive.stat().st_size >= MIN_SIZE:
                break
            archive.unlink(missing_ok=True)
        else:
            log("所有下载源均失败，请手动下载完整构建包并解压 mpv.exe 到 app/players/")
            return 1
        if not extract_exe(archive, EXE):
            return 1
        if not (EXE.exists() and EXE.stat().st_size >= MIN_SIZE):
            log(f"提取结果异常: {EXE} size={EXE.stat().st_size if EXE.exists() else 'missing'}")
            return 1
        log(f"完成: {EXE} ({EXE.stat().st_size / 1024 / 1024:.1f} MB)")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
