"""Windows 桌面壁纸设置 + 轮播调度。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import random
import sys
from pathlib import Path

SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02

user32 = ctypes.windll.user32
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT,
                                         wintypes.LPWSTR, wintypes.INT]
user32.SystemParametersInfoW.restype = wintypes.BOOL

STYLE_MAP = {
    # style -> (WallpaperStyle, TileWallpaper)
    "center": ("0", "0"),
    "tile": ("0", "1"),
    "stretch": ("2", "0"),
    "fit": ("6", "0"),
    "fill": ("10", "0"),
    "span": ("22", "0"),
}


def _set_registry_style(style: str) -> None:
    wstyle, tile = STYLE_MAP.get(style, STYLE_MAP["fill"])
    import winreg
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE
    )
    with key:
        winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, wstyle)
        winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, tile)


def set_wallpaper(image_path: str, style: str = "fill") -> bool:
    """把图片设置为桌面壁纸（所有显示器同一张，或 span 跨屏）。"""
    p = str(Path(image_path).resolve())
    if not Path(p).exists():
        return False
    try:
        if sys.platform == "win32":
            _set_registry_style(style)
            ok = ctypes.windll.user32.SystemParametersInfoW(
                SPI_SETDESKWALLPAPER, 0, p, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
            )
            return bool(ok)
    except Exception:
        return False
    return False


class Slideshow:
    """定时轮播：按配置从库/收藏/指定文件夹随机换壁纸。"""

    def __init__(self, config, library, on_change=None):
        self.config = config
        self.library = library
        self.on_change = on_change  # callable(path)
        self._pool: list[str] = []
        self._idx = 0

    def _build_pool(self) -> list[str]:
        source = self.config.get("slideshow_source", "library")
        if source == "favorites":
            entries = self.library.favorites()
        elif source == "folder":
            folder = self.config.get("slideshow_folder", "")
            entries = self.library.in_folder(folder) if folder else []
        else:
            entries = self.library.images()
        return [e.path for e in entries if e.type == "image"]

    def next_wallpaper(self, random_pick: bool = True) -> str | None:
        pool = self._build_pool()
        if not pool:
            return None
        if random_pick:
            path = random.choice(pool)
        else:
            self._idx = (self._idx + 1) % len(pool)
            path = pool[self._idx]
        style = self.config.style
        if set_wallpaper(path, style):
            self.config.set("current_wallpaper", path)
            self.config.set("current_wallpaper_type", "image")
            if self.on_change:
                self.on_change(path)
            return path
        return None
