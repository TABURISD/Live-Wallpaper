"""程序入口：python -m app

架构：
- GUI 线程（子线程）：QApplication + 托盘 + 快捷键 + mpv 视频壁纸 + Flask 本地 API
- 主线程：pywebview (WebView2) 窗口承载网页 UI
- 没有 WebView2 时回退系统浏览器；--classic 使用旧 Qt 界面

单实例：第二个实例启动时唤醒已有窗口并退出。
"""
from __future__ import annotations

import os
import sys
import threading
import time

SINGLE_ID = "MeWallpaper_SingleInstance_0x1"


def _notify_existing() -> bool:
    """尝试连接已有实例；成功则唤醒并返回 True。"""
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(SINGLE_ID)
    if sock.waitForConnected(300):
        sock.write(b"raise")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.close()
        return True
    return False


_MUTEX_HANDLES: list = []   # 持有互斥体句柄引用，防止被回收


def _forward_to_running() -> None:
    """已有实例在跑：把 --set-video 转发给它（尽力而为），随后本实例退出。"""
    if "--set-video" not in sys.argv:
        return
    try:
        import json, urllib.request
        from .webapi import PORT
        vpath = sys.argv[sys.argv.index("--set-video") + 1]
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/api/set",
            data=json.dumps({"path": vpath}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass


def main() -> int:
    # ---- 单实例第一道防线：内核互斥体 ----
    # 不依赖对方 Qt 事件循环的响应速度。QLocalSocket 方案在对方 GUI 线程
    # 忙（模态框 exec / SPI 阻塞）时会连接超时放行，实测出现过三实例并行，
    # 多实例抢同一个 WorkerW 必然互踩闪屏乃至崩溃。互斥体由内核持有，
    # 只要对方进程活着就 100% 拦下。
    import ctypes
    _kernel32 = ctypes.windll.kernel32
    _mutex = _kernel32.CreateMutexW(None, False,
                                    "Local\\MeWallpaper_SingleInstance_0x2")
    if _kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        _forward_to_running()
        return 0
    _MUTEX_HANDLES.append(_mutex)

    from PySide6.QtCore import Qt
    try:
        QApplication_set_policy = Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    except Exception:
        QApplication_set_policy = None

    from PySide6.QtNetwork import QLocalServer

    # ---- GUI 线程：Qt 事件循环（隐藏核心 + 托盘 + 视频壁纸 + API）----
    ready = threading.Event()
    state: dict = {"win": None}

    def qt_thread():
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        if QApplication_set_policy is not None:
            try:
                QApplication.setHighDpiScaleFactorRoundingPolicy(
                    QApplication_set_policy)
            except Exception:
                pass
        app = QApplication(sys.argv)
        app.setApplicationName("MeWallpaper")
        app.setQuitOnLastWindowClosed(False)
        from .ui.theme import apply_theme
        app.setStyle("Fusion")
        apply_theme(app)

        server = QLocalServer()
        if _notify_existing():
            os._exit(0)
        QLocalServer.removeServer(SINGLE_ID)
        server.listen(SINGLE_ID)

        from .ui.main_window import MainWindow
        win = MainWindow()
        state["win"] = win
        server.newConnection.connect(lambda: _on_new_conn(server, win))

        # Web API（Flask 线程内运行）
        from . import webapi
        webapi.start_server(win)
        url = f"http://127.0.0.1:{webapi.PORT}/"

        classic = "--classic" in sys.argv
        win._web_mode = not classic
        if classic:
            win._open_ui = None
            win.show()
        else:
            # Web 模式：核心窗口隐藏且改标题，避免和 WebView2 窗口重名
            # 导致 FindWindow 找到隐藏窗口、托盘唤起「没反应」
            win.setWindowTitle("MeWallpaperCore")
            win._open_ui = make_show_or_raise(url)

        # 启动参数：--set-video <路径> 启动后自动应用动态壁纸
        if "--set-video" in sys.argv:
            try:
                vpath = sys.argv[sys.argv.index("--set-video") + 1]
                # 与 MainWindow 自动恢复同理：禁用 singleShot 定时器，
                # 只登记 pending，由 _wv_timer 首 tick 一次性消费，
                # 防止嵌套事件循环里鬼影重挂
                win._pending_restore = vpath
            except Exception:
                pass
        ready.set()
        app.exec()

    threading.Thread(target=qt_thread, daemon=True).start()
    if not ready.wait(20):
        print("GUI 线程启动超时", file=sys.stderr)
        return 1

    win = state["win"]
    if "--classic" in sys.argv:
        # 经典模式：主线程只需保活（Qt 在子线程跑）
        while True:
            time.sleep(3600)

    # ---- 主线程：WebView2 窗口 ----
    url = f"http://127.0.0.1:{webapi_PORT()}/"

    def create_window(webview):
        w = webview.create_window(
            "MeWallpaper", url, width=1240, height=800,
            min_size=(880, 560), background_color="#eef1f7")
        w.events.closed += on_closed
        from . import webapi
        webapi.WEBVIEW_WINDOWS.append(w)
        return w

    quitting = {"on": False}

    def on_closed():
        # 关窗 ≈ 最小化到托盘：重建一个最小化的窗口（除非正在退出）
        if quitting["on"]:
            return
        try:
            time.sleep(0.25)
            create_window(webview).minimize()
        except Exception:
            pass

    def before_quit():
        quitting["on"] = True

    win._before_quit = before_quit

    try:
        import webview
    except Exception:
        webview = None
    if webview is None:
        import webbrowser
        webbrowser.open(url)
        while True:
            time.sleep(3600)
    create_window(webview)

    # 窗口出现后设置任务栏/标题栏图标（logo.ico）
    def _set_window_icon():
        from .config import PROJECT_ROOT
        ico = PROJECT_ROOT / "web" / "assets" / "logo.ico"
        if not ico.exists():
            return
        import ctypes
        u32 = ctypes.windll.user32
        for _ in range(60):
            h = u32.FindWindowW(None, "MeWallpaper")
            if h:
                hi = u32.LoadImageW(0, str(ico), 1, 0, 0, 0x10)  # IMAGE_ICON | LR_LOADFROMFILE
                if hi:
                    u32.SendMessageW(h, 0x0080, 1, hi)  # WM_SETICON ICON_BIG
                    u32.SendMessageW(h, 0x0080, 0, hi)  # WM_SETICON ICON_SMALL
                return
            time.sleep(0.5)
    threading.Thread(target=_set_window_icon, daemon=True).start()

    webview.start()          # 阻塞主线程；所有窗口关闭且非退出时由 on_closed 重建
    # start() 返回 = WebView2 层窗口全部关闭。这不是退出信号：动态壁纸、
    # 托盘和 Qt 核心都还活着（此前 WebView2 崩溃或窗口重建失败时进程
    # 直接整体退出，表现为「闪退」）。非正常返回时保持进程常驻。
    if not quitting["on"]:
        from . import flicklog
        flicklog.log("webview.start returned without quit; keep process alive")
        while True:
            time.sleep(3600)
    return 0


def webapi_PORT() -> int:
    from . import webapi
    return webapi.PORT


def make_show_or_raise(url: str):
    """托盘/单实例「打开界面」：WebView2 窗口存在就置顶，否则用浏览器兜底。"""
    import ctypes

    def show_or_raise():
        try:
            u32 = ctypes.windll.user32
            hwnd = u32.FindWindowW(None, "MeWallpaper")
            if hwnd:
                u32.ShowWindow(hwnd, 9)            # SW_RESTORE
                u32.SetForegroundWindow(hwnd)
                return
        except Exception:
            pass
        import webbrowser
        webbrowser.open(url)

    return show_or_raise


def _on_new_conn(server, win):
    sock = server.nextPendingConnection()
    if sock:
        sock.waitForReadyRead(200)
        sock.close()
    win._show_ui()


if __name__ == "__main__":
    sys.exit(main())
