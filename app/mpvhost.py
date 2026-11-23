"""mpv 专用原生宿主窗口。

mpv 的 wid 嵌入需要一个 Qt 完全不参与绘制的纯 Win32 HWND：实测 Qt 的
QWidget（哪怕 WA_NativeWindow）会把 mpv 的画面压在自己后备存储之下，
窗口永远黑/空白；而原生 HWND 渲染正常。因此给 mpv 单独建一个系统
STATIC(SS_BLACKRECT) 子窗口——不经手任何自定义 wndproc，避免回调在
非主线程被系统调用时的崩溃面；Qt 只负责外层窗口的几何与生命周期。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR,
                                   wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE,
                                   wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL


def create(parent_hwnd: int) -> int:
    """在 parent_hwnd 客户区内创建一个铺满的黑色子窗口，返回 HWND。"""
    hwnd = user32.CreateWindowExW(
        0, "STATIC", None,
        0x50000000        # WS_CHILD | WS_VISIBLE
        | 0x00000004,      # SS_BLACKRECT：系统绘制的纯黑矩形，无文本无回调
        0, 0, 8, 8,
        int(parent_hwnd), None, None, None)
    return int(hwnd)


def sync(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    """把宿主窗口移动到父窗口客户区指定位置（物理像素）。"""
    user32.SetWindowPos(int(hwnd), 0, int(x), int(y), int(w), int(h),
                        0x0014)  # NOZORDER | NOACTIVATE


def destroy(hwnd: int) -> None:
    user32.DestroyWindow(int(hwnd))
