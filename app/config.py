"""本地配置与数据目录管理。所有数据都存在本地，不依赖任何线上数据库。"""
from __future__ import annotations

import json
import os
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv"}

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _pick_data_dir() -> Path:
    """数据目录：优先项目内 data/；安装到 Program Files 等只读位置时，
    自动切换到 %LOCALAPPDATA%\\MeWallpaper\\data，保证配置/缓存可写。"""
    local = PROJECT_ROOT / "data"
    try:
        local.mkdir(parents=True, exist_ok=True)
        probe = local / ".writetest"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return local
    except Exception:
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        d = base / "MeWallpaper" / "data"
        d.mkdir(parents=True, exist_ok=True)
        # 免安装版（项目内 data/ 可写）升级到安装版时，迁移已有配置/壁纸库/缩略图
        if local.exists() and not (d / "config.json").exists():
            import shutil
            for name in ("config.json", "library.json"):
                src = local / name
                if src.exists():
                    try:
                        shutil.copy2(src, d / name)
                    except Exception:
                        pass
            for sub in ("thumbs", "downloads"):
                src = local / sub
                if src.exists():
                    try:
                        shutil.copytree(src, d / sub, dirs_exist_ok=True)
                    except Exception:
                        pass
        return d


DATA_DIR = _pick_data_dir()
THUMB_DIR = DATA_DIR / "thumbs"
CACHE_DIR = DATA_DIR / "cache"
LIBRARY_FILE = DATA_DIR / "library.json"
CONFIG_FILE = DATA_DIR / "config.json"
DOWNLOAD_DIR = DATA_DIR / "downloads"


def ensure_dirs() -> None:
    for d in (DATA_DIR, THUMB_DIR, CACHE_DIR, DOWNLOAD_DIR):
        d.mkdir(parents=True, exist_ok=True)


DEFAULT_CONFIG = {
    # 壁纸填充方式: stretch 拉伸 / fit 适应 / fill 填充 / tile 平铺 / center 居中 / span 跨屏
    "wallpaper_style": "fill",
    # 轮播
    "slideshow_enabled": False,
    "slideshow_minutes": 30,
    "slideshow_source": "library",   # library=全部  favorites=仅收藏  folder=指定文件夹
    "slideshow_folder": "",
    # 在线源
    "proxy": "",                     # 留空则自动读取系统代理；设为 "direct" 强制直连
    "wallhaven_api_key": "",
    "wallhaven_categories": "110",   # general/anime/people
    "wallhaven_purity": "100",       # sfw only
    "wallhaven_sorting": "favorites",
    "download_resolution_min": "1920x1080",
    # 视频壁纸
    "video_volume": 0,
    "video_hw_decode": True,
    "video_paused_on_fullscreen": True,
    "video_stretch": False,
    "video_loop": True,
    # 下载/存储目录（在线壁纸保存位置）
    "download_dir": r"E:\LiveWallpaper",
    # 行为
    "auto_start": False,
    # 自动纳入壁纸库的文件夹（可多个）
    "watch_folders": [],
    "current_wallpaper": "",          # 当前壁纸路径（图片或视频）
    "current_wallpaper_type": "image",
}


class Config:
    def __init__(self) -> None:
        ensure_dirs()
        self.data: dict = dict(DEFAULT_CONFIG)
        self.load()

    def load(self) -> None:
        if CONFIG_FILE.exists():
            try:
                self.data.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
            except Exception:
                pass

    def save(self) -> None:
        ensure_dirs()
        CONFIG_FILE.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()

    # ---- 便捷属性 ----
    @property
    def style(self) -> str:
        return str(self.get("wallpaper_style", "fill"))
