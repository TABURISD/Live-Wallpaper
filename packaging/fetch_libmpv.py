# -*- coding: utf-8 -*-
"""下载 mpv 官方 Windows 构建（dev 包）并提取 libmpv-2.dll 到 app/players/。

libmpv-2.dll 体积约 116 MB，超出 GitHub 单文件 100 MB 限制，不入库；
构建前由本脚本自动获取（GitHub 直连，失败时走公开加速镜像）。

来源：shinchiro/mpv-winbuild-cmake（mpv 官方 Windows 构建）
许可证：见 licenses/THIRD-PARTY-LICENSES.md
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DLL_DIR = ROOT / "app" / "players"
DLL = DLL_DIR / "libmpv-2.dll"

RELEASE = "20261111"
ASSET = f"mpv-dev-x86_64-{RELEASE}-git-bcde6b93cc.7z"
GH_URL = (
    "https://github.com/shinchiro/mpv-winbuild-cmake/releases/"
    f"download/{RELEASE}/{ASSET}"
)
MIRRORS = [
    "https://ghfast.top/" + GH_URL,
    "https://gh-proxy.com/" + GH_URL,
]

# libmpv-2.dll 期望大小区间（用于校验下载完整性）
MIN_SIZE = 80 * 1024 * 1024


def log(msg: str) -> None:
    print(f"[fetch-libmpv] {msg}", flush=True)


def download(url: str, dest: Path) -> bool:
    log(f"下载 {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MeWallpaper-build"})
        with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f, 1024 * 256)
    except Exception as e:  # noqa: BLE001
        log(f"失败: {e}")
        return False
    size = dest.stat().st_size
    log(f"已下载 {size / 1048576:.1f} MB")
    return size > MIN_SIZE


def extract(archive: Path) -> Path | None:
    """用系统 bsdtar 解 7z，返回 libmpv DLL 路径。"""
    stage = Path(tempfile.mkdtemp(prefix="libmpv_"))
    try:
        r = subprocess.run(
            ["tar", "-xf", str(archive), "-C", str(stage)],
            capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            log(f"解包失败: {r.stderr[:300]}")
            return None
        for p in stage.rglob("*.dll"):
            if p.stem in ("libmpv-2", "mpv-2", "mpv-1"):
                return p
        log("压缩包中未找到 libmpv DLL")
        return None
    except Exception as e:  # noqa: BLE001
        log(f"解包异常: {e}")
        return None


def main() -> int:
    if DLL.exists() and DLL.stat().st_size > MIN_SIZE:
        log(f"已存在 {DLL.stat().st_size / 1048576:.1f} MB，跳过")
        return 0
    DLL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DLL_DIR / "_libmpv.7z"
    ok = False
    for url in [GH_URL, *MIRRORS]:
        if download(url, tmp):
            ok = True
            break
    if not ok:
        log("所有下载源均失败，请手动下载 dev 包并解压 libmpv-2.dll 到 app/players/")
        return 1
    dll = extract(tmp)
    tmp.unlink(missing_ok=True)
    if not dll:
        return 1
    shutil.copy2(dll, DLL)
    log(f"OK: {DLL} ({DLL.stat().st_size / 1048576:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
