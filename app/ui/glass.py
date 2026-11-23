"""Win11 液态玻璃（DWM 亚克力背景）支持。

- DWMWA_SYSTEMBACKDROP_TYPE (38) = 4 → Acrylic 亚克力背景
- DWMWA_USE_IMMERSIVE_DARK_MODE (20) = 1 → 暗色标题栏/边框
- DWMWA_WINDOW_CORNER_PREFERENCE (33) = 2 → 圆角窗口

非 Win11（build < 22000）返回 False，调用方回退到纯色深色。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38

DWMWCP_ROUND = 2
DWMSBT_ACRYLIC = 4

MARGINS = wintypes.INT * 5


def is_win11() -> bool:
    return sys.platform == "win32" and sys.getwindowsversion().build >= 22000


_dwm = ctypes.windll.dwmapi
_dwm.DwmSetWindowAttribute.argtypes = [
    wintypes.HWND, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
_dwm.DwmSetWindowAttribute.restype = ctypes.c_long
# 注意：用 c_void_p 而不是具体数组类型，避免和 pywebview 等库
# 对同一全局函数原型设置 argtypes 时互相覆盖导致 ctypes 报错
_dwm.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.c_void_p]
_dwm.DwmExtendFrameIntoClientArea.restype = ctypes.c_long


def _set_attr(hwnd: int, attr: int, value: int) -> bool:
    val = ctypes.c_int(value)
    hr = _dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
    return hr == 0


def enable_glass(hwnd: int) -> bool:
    """给窗口开启亚克力背景 + 暗色 + 圆角。仅 Win11 有效。"""
    if not is_win11() or not hwnd:
        return False
    _set_attr(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
    _set_attr(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
    ok = _set_attr(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_ACRYLIC)
    # 把帧扩展到整个客户区，让亚克力透出来
    m = MARGINS(-1, -1, -1, -1, -1)
    _dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))
    return ok
