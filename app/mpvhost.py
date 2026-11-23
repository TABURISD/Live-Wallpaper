"""mpv 专用原生宿主窗口。

mpv 的 wid 嵌入需要一个 Qt 完全不参与绘制的纯 Win32 HWND：实测 Qt 的
QWidget（哪怕 WA_NativeWindow）会把 mpv 的画面压在自己后备存储之下，
窗口永远黑/空白；而原生 HWND 渲染正常。因此给 mpv 单独建一个 Static 风格
子窗口，Qt 只负责外层窗口的生命周期和几何，画面全部由 mpv 直接呈现。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t

_CLASS = "MeWallpaperMpvHost"
_registered = False


def _register() -> None:
    global _registered
    if _registered:
        return

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND,
                                 wintypes.UINT, wintypes.WPARAM,
                                 wintypes.LPARAM)

    @WNDPROC
    def _wndproc(hwnd, msg, wp, lp):  # noqa: ANN001
        if msg == 0x0002:  # WM_DESTROY
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    # 防止 GC 回收回调
    _wndproc._keep = _wndproc

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT),
                    ("lpfnWndProc", ctypes.c_void_p),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR)]

    kernel32 = ctypes.windll.kernel32
    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    hinst = kernel32.GetModuleHandleW(None)
    cls = WNDCLASSW()
    cls.lpfnWndProc = ctypes.cast(_wndproc, ctypes.c_void_p)
    cls.hInstance = hinst
    cls.hbrBackground = gdi32.GetStockObject(4)  # BLACK_BRUSH
    cls.lpszClassName = _CLASS
    user32.RegisterClassW(ctypes.byref(cls))
    _registered = True


def create(parent_hwnd: int) -> int:
    """在 parent_hwnd 客户区内创建一个铺满的可见子窗口，返回 HWND。"""
    _register()
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR,
                                       wintypes.LPCWSTR, wintypes.DWORD,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, wintypes.HWND,
                                       wintypes.HMENU, wintypes.HINSTANCE,
                                       wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    hwnd = user32.CreateWindowExW(
        0, _CLASS, None,
        0x50000000 | 0x02000000,  # WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS
        0, 0, 8, 8,
        int(parent_hwnd), None, None, None)
    return int(hwnd)


def sync(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    """把宿主窗口移动到父窗口客户区指定位置（物理像素）。"""
    user32.SetWindowPos(int(hwnd), 0, int(x), int(y), int(w), int(h),
                        0x0014)  # NOZORDER | NOACTIVATE


def destroy(hwnd: int) -> None:
    user32.DestroyWindow(int(hwnd))
