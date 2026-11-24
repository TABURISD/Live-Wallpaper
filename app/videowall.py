"""视频动态壁纸：把无边框播放窗口挂到 WorkerW 桌面层（图标与壁纸之间）。

原理：给 Progman 发 0x052C 产生 WorkerW，再把播放窗口 SetParent 进去。
实验性功能：依赖 Qt Multimedia 后端与系统解码器。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

PROGMAN = "Progman"
WORKERW = "WorkerW"

MSG_SPAWN_WORKERW = 0x052C
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

user32 = ctypes.windll.user32

# ---- 严格的函数原型：64 位句柄必须按指针宽度传，否则 OverflowError ----
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(wintypes.DWORD),
]
user32.SendMessageTimeoutW.restype = wintypes.LPARAM
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
# 64 位必须用 Ptr 版本（LONG_PTR = 指针宽度整数）
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = wintypes.LPARAM
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LPARAM]
user32.SetWindowLongPtrW.restype = wintypes.LPARAM
user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
user32.SetParent.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL


def _enum_windows_by_class(cls: str) -> list[int]:
    result: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value == cls:
            result.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return result


def _children_of(hwnd: int) -> list[int]:
    out: list[int] = []
    child = user32.GetWindow(hwnd, 5)   # GW_CHILD
    while child:
        out.append(child)
        child = user32.GetWindow(child, 2)  # GW_HWNDNEXT
    return out


def _rect_area(hwnd: int) -> int:
    rc = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    return max(0, rc.right - rc.left) * max(0, rc.bottom - rc.top)


def find_workerw() -> int:
    """找到桌面壁纸层的 WorkerW 句柄。

    Win11 上真正的 WorkerW 是 Progman 的“可见、全屏”子窗口；
    顶层也能枚举到一堆同名小窗口（其他软件创建的），不能选。
    """
    progman = user32.FindWindowW(PROGMAN, None)
    if not progman:
        return 0
    # 确保 0x052C 已发送（幂等）
    res = wintypes.DWORD(0)
    user32.SendMessageTimeoutW(
        progman, MSG_SPAWN_WORKERW, 0, 0, 0x0002, 1000, ctypes.byref(res))

    candidates: list[int] = []
    progman_children: set[int] = set()
    # 1) Progman 子窗口里的 WorkerW（Win11 正主在这里）
    for child in _children_of(progman):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(child, buf, 256)
        if buf.value == WORKERW:
            candidates.append(child)
            progman_children.add(child)
    # 2) 顶层 WorkerW（旧系统路径；也可能是其他软件造的同名层）
    for h in _enum_windows_by_class(WORKERW):
        if h not in progman_children:
            candidates.append(h)

    if not candidates:
        return 0
    # 确定性选择：可见 > 面积最大 > Progman 子窗口（真壁纸层）> 句柄序。
    # 不使用纯枚举序做决胜——枚举顺序跨调用不稳定，同分时会每次换目标，
    # 把壁纸窗口在不同 WorkerW 层之间搬来搬去（闪屏 + 句柄失效）。
    candidates.sort(key=lambda h: (user32.IsWindowVisible(h),
                                   _rect_area(h),
                                   h in progman_children,
                                   h))
    return candidates[-1]


def find_workerw_stable() -> int:
    """返回上次用过的 WorkerW（若仍有效），否则重新找。

    find_workerw() 每次重选可能因可见性/面积变化而换目标（本机顶层有
    十余个同名 WorkerW），把壁纸窗口移来移去后 quick_check 永远失败，
    保活陷入每 1.5s 一次的重挂死循环。嵌入目标必须稳定，只在句柄失效
    （Explorer 重启）时才重新发现。
    """
    global _last_workerw
    if _last_workerw and user32.IsWindow(_last_workerw):
        return _last_workerw
    return find_workerw()


_last_workerw: int = 0


class VideoWallpaperWindow:  # QObject 由调用方组装，这里只做 Win32 嵌入
    @staticmethod
    def attach(qwindow, stretch: bool = True) -> bool:
        global _last_workerw
        from . import flicklog
        flicklog.log(f"attach enter hwnd={int(qwindow.winId())}")
        hwnd = int(qwindow.winId())
        workerw = find_workerw_stable()
        flicklog.log(f"attach workerw={workerw}")
        if not workerw:
            return False
        _last_workerw = int(workerw)
        # 样式：无边框、子窗口、不抢焦点、不出现在任务栏/Alt-Tab
        style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        style = (style & ~WS_POPUP) | WS_CHILD | WS_VISIBLE
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
        exstyle = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE,
                                 exstyle | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        user32.SetParent(hwnd, workerw)
        # 几何完全由 Qt 层（setGeometry）决定；这里只保证层级/可见性，
        # 避免 Win32 坐标（含 DPI 差异）和 Qt 内部状态互相覆盖。
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                            0x0057)  # NOMOVE|NOSIZE|NOZORDER|NOACTIVATE|SHOWWINDOW
        # 一次性压到 WorkerW 子窗口栈最底（图标层之下）。
        # 注意：对 flip 交换链的任何 Z-order 操作都是一次闪屏，
        # 所以只在嵌入这一刻做一次，之后靠保活的「非必要不动手」维持。
        user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0,
                            0x0013)  # HWND_BOTTOM | NOMOVE|NOSIZE|NOACTIVATE
        user32.ShowWindow(hwnd, 5)                        # SW_SHOW 兜底（SetParent 会清可见性）
        return True

    @staticmethod
    def detach(qwindow) -> None:
        hwnd = int(qwindow.winId())
        user32.SetParent(hwnd, 0)
        style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, (style & ~WS_CHILD) | WS_POPUP)

    @staticmethod
    def is_still_attached(qwindow) -> bool:
        hwnd = int(qwindow.winId())
        workerw = find_workerw()
        return bool(workerw) and user32.GetParent(hwnd) == workerw \
            and user32.IsWindowVisible(hwnd)

    @staticmethod
    def quick_check(qwindow) -> bool:
        """不打探系统消息的轻量自检：父窗口还是 WorkerW 且可见。

        供定时保活用——绝不能每 1.5s 调 find_workerw()（它给 Progman 发
        0x052C，且随后的 SetWindowPos 会把 flip 交换链踢出独立翻转平面，
        两者都会造成周期性闪屏）。
        """
        hwnd = int(qwindow.winId())
        return bool(_last_workerw) \
            and user32.GetParent(hwnd) == _last_workerw \
            and user32.IsWindowVisible(hwnd)

    @staticmethod
    def is_bottom_child(qwindow) -> bool:
        """壁纸窗口是否已是 WorkerW 的最底层子窗口（图标层之下）。

        注意：GetWindow(GW_HWNDLAST) 取的是「兄弟窗口」链的末尾，
        直接对父窗口调用返回的不是最底层子窗口（本机实测返回父窗口自身，
        导致 is_bottom_child 恒假、保活每 1.5s 压底一次 → 周期性闪屏）。
        正确做法：先 GW_CHILD 取第一个子窗口，再对它的兄弟链取 GW_HWNDLAST。
        """
        hwnd = int(qwindow.winId())
        if not _last_workerw:
            return True
        first = user32.GetWindow(_last_workerw, 5)   # GW_CHILD
        if not first:
            return True
        bottom = user32.GetWindow(first, 1)          # GW_HWNDLAST（兄弟链）
        return int(bottom) == hwnd
