"""主窗口：标签页 + 托盘 + 轮播 + 快捷键 + 视频壁纸调度。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPoint
from PySide6.QtGui import QAction, QCloseEvent, QColor, QIcon, QPainter, QPixmap, QPixmapCache
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton,
    QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget,
)

from .. import APP_NAME_CN
from ..config import Config, PROJECT_ROOT
from ..library import Library
from ..wallpaper import Slideshow, set_wallpaper
from .. import videowall
from .. import mpvbackend
from .. import mpvhost
from ..sources import autodetect_proxy, set_proxy
from .anim import fade_in
from .glass import enable_glass, is_win11
from .static_tab import StaticTab
from .video_tab import VideoTab
from .online_tab import OnlineTab
from .settings_tab import SettingsTab
from .thumbs import ThumbLoader

HOTKEY_NEXT_ID = 1001
MOD_CONTROL, MOD_ALT = 0x0002, 0x0001
VK_N = 0x4E

# ---- Win32 原型声明（64 位句柄安全）----
user32 = ctypes.windll.user32
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _MINMAXINFO(ctypes.Structure):
    _fields_ = [("ptReserved", _POINT), ("ptMaxSize", _POINT),
                ("ptMaxPosition", _POINT), ("ptMinTrackSize", _POINT),
                ("ptMaxTrackSize", _POINT)]


class _RECT_S(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT_S),
                ("rcWork", _RECT_S), ("dwFlags", wintypes.DWORD)]


user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HWND
user32.GetMonitorInfoW.argtypes = [wintypes.HWND, ctypes.POINTER(_MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL


class TitleBar(QWidget):
    """自绘标题栏：图标 + 标题 + 最小化/最大化/关闭。双击切换最大化。"""

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self._win = window
        self.setObjectName("titleBar")
        self.setFixedHeight(38)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 4, 0)
        lay.setSpacing(6)

        self.icon = QLabel()
        self.icon.setObjectName("titleIcon")
        self.icon.setFixedSize(18, 18)
        icon_path = PROJECT_ROOT / "app" / "icon.ico"
        if icon_path.exists():
            self.icon.setPixmap(QIcon(str(icon_path)).pixmap(18, 18))
        lay.addWidget(self.icon)

        self.title = QLabel(APP_NAME_CN)
        self.title.setObjectName("titleLabel")
        lay.addWidget(self.title)
        lay.addStretch(1)

        for name, text, tip, slot in (
            ("btnMin", "🗕", "最小化", self._minimize),
            ("btnMax", "🗖", "最大化", self._toggle_max),
            ("btnClose", "✕", "关闭", self._close),
        ):
            btn = QPushButton(text)
            btn.setObjectName(name)
            btn.setToolTip(tip)
            btn.setFixedSize(40, 30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            lay.addWidget(btn)

    def _minimize(self):
        self._win.showMinimized()

    def _toggle_max(self):
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()

    def _close(self):
        self._win.close()

    def mouseDoubleClickEvent(self, event):
        self._toggle_max()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._win.isMaximized():
            self._drag_pos = event.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
        else:
            self._drag_pos = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._drag_pos is not None
                and event.buttons() & Qt.MouseButton.LeftButton
                and not self._win.isMaximized()):
            self._win.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)


class VideoPlayerWindow(QMainWindow):
    """无边框播放窗口，挂到 WorkerW 后成为动态壁纸。

    后端优先 mpv (libmpv，硬解、通吃编码)；
    没有 libmpv-2.dll 时回退 Qt Multimedia。
    """

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnBottomHint)
        # mpv 直接渲染进原生 HWND，用黑色 QWidget 做画布；
        # Qt 兜底路径会把它换成 QVideoWidget
        self.surface = QWidget()
        self.surface.setObjectName("videoSurface")
        self.surface.setStyleSheet("background:#000;")
        # mpv 直接渲染进原生 HWND：禁止 Qt 擦除背景，
        # 否则系统重绘/Explorer 刷新时 Qt 会用底色覆盖交换链 → 周期性闪黑
        self.surface.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.surface.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setCentralWidget(self.surface)
        self.backend = "mpv" if mpvbackend.backend_available() else "qt"
        self._mpv: mpvbackend.MpvPlayer | None = None
        self._mpv_host: int | None = None   # mpv 渲染专用的纯 Win32 子窗口 HWND
        self._qt_player = None
        self._qt_audio = None
        self._mpv_fit_timer: QTimer | None = None
        self._fit_preview_done = False
        self._loop = True
        self.attached = False
        # 预览前是否正挂着桌面壁纸：是的话，预览关闭后由 on_preview_closed 恢复
        self._resume_wallpaper = False
        self.on_preview_closed = None

    def closeEvent(self, e):
        # 预览模式点标题栏 ✕：停播并隐藏，窗口对象保留给壁纸模式复用；
        # 壁纸模式（attached）下忽略关闭，避免误操作把壁纸弄丢。
        if self.attached:
            e.ignore()
            return
        resume = self._resume_wallpaper
        self._resume_wallpaper = False
        try:
            self.stop()
        except Exception:
            pass
        e.ignore()
        self.hide()
        # 预览期间临时摘下了桌面壁纸：关预览时自动挂回去
        if resume and callable(self.on_preview_closed):
            try:
                self.on_preview_closed()
            except Exception:
                pass

    # ---------- mpv 原生宿主窗口 ----------
    def _ensure_mpv_host(self) -> int:
        """创建/复用 mpv 渲染专用的纯 Win32 子窗口，返回 HWND。

        Qt 的 QWidget 会把自己的后备存储合成在原生内容之上，mpv 直接渲染
        进 QWidget 的 HWND 会被盖住（实测全黑）；原生 Static 风格子窗口
        则完全由 mpv 呈现，Qt 只负责外层窗口的几何与生命周期。
        """
        if self._mpv_host:
            return self._mpv_host
        self._mpv_host = mpvhost.create(int(self.winId()))
        self._sync_mpv_host()
        return self._mpv_host

    def _sync_mpv_host(self):
        if not self._mpv_host:
            return
        try:
            dpr = self.devicePixelRatioF()
            mpvhost.sync(self._mpv_host, 0, 0,
                         int(self.width() * dpr), int(self.height() * dpr))
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_mpv_host()

    # ---------- Qt 兜底后端 ----------
    def _ensure_qt_player(self):
        if self._qt_player is not None:
            return
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget
        vw = QVideoWidget()
        self.setCentralWidget(vw)
        self.surface = vw
        self._qt_audio = QAudioOutput()
        self._qt_player = QMediaPlayer()
        self._qt_player.setAudioOutput(self._qt_audio)
        self._qt_player.setVideoOutput(vw)
        self._qt_player.mediaStatusChanged.connect(self._on_status)

    def _on_status(self, status):
        from PySide6.QtMultimedia import QMediaPlayer
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self._loop:
            self._qt_player.setPosition(0)
            self._qt_player.play()

    # ---------- 播放控制 ----------
    def play(self, path: str, volume: int, stretch: bool, hwdec: bool = True,
             loop: bool = True, style: str = "fill") -> bool:
        from PySide6.QtGui import QGuiApplication
        # 壁纸模式：贴底 + 无边框（窗口属性在 Qt 层改，随后 Win32 再嵌入 WorkerW）
        flags = self.windowFlags() | Qt.WindowType.FramelessWindowHint \
            | Qt.WindowType.WindowStaysOnBottomHint
        self.setWindowFlags(flags)
        self._loop = loop
        self.show()
        # 几何在 Qt 层定好：铺满虚拟屏幕（多显示器）或仅主屏居中。
        # 这样 attach() 里的 SetParent 不会把窗口挤到错误位置。
        screen = QGuiApplication.primaryScreen()
        rect = screen.virtualGeometry() if stretch else screen.geometry()
        self.setGeometry(rect)
        if self.backend == "mpv" and self._mpv is None:
            try:
                self._mpv = mpvbackend.MpvPlayer(
                    self._ensure_mpv_host(), hwdec=hwdec, volume=volume,
                    loop=loop)
            except Exception:
                self._mpv = None
                self.backend = "qt"      # mpv 子进程拉不起来，降级 Qt 兜底
        if self.backend == "mpv" and self._mpv is not None:
            self._mpv.set_loop(loop)
            self._mpv.set_volume(volume)
            self._mpv.set_fill_mode(style)   # 填充方式对动态壁纸同样生效
            self._mpv.resume()
            self._mpv.play(path)
        else:
            from PySide6.QtCore import QUrl
            self._ensure_qt_player()
            self._qt_player.setSource(QUrl.fromLocalFile(path))
            self._qt_audio.setVolume(volume / 100.0)
            self._qt_player.play()
        ok = videowall.VideoWallpaperWindow.attach(self, stretch=stretch)
        self.attached = ok
        return ok

    def preview(self, path: str, volume: int = 0, hwdec: bool = True,
                loop: bool = True):
        """窗口内预览（不嵌入桌面）。窗口尺寸跟随视频真实比例。"""
        # 若当前正嵌入桌面层（WorkerW），先脱离再弹预览窗，
        # 否则窗口还是 WorkerW 子窗口，预览会显示在错误层级/位置。
        self._resume_wallpaper = self.attached
        if self.attached:
            try:
                videowall.VideoWallpaperWindow.detach(self)
            except Exception:
                pass
        # 预览必须出现在最前：清掉壁纸模式用的「贴底」标志，否则窗口
        # 永远压在 WebView2/其他窗口下面，用户以为「预览没反应」。
        # 用带系统标题栏的普通窗口：原生 ✕ 关闭按钮最可靠，
        # 还能拖动/调整大小；置顶保证预览不被压在下面。
        flags = (self.windowFlags()
                 | Qt.WindowType.WindowStaysOnTopHint) \
            & ~Qt.WindowType.FramelessWindowHint \
            & ~Qt.WindowType.WindowStaysOnBottomHint
        self.setWindowFlags(flags)
        self._loop = loop
        self.setWindowTitle(f"预览 - {Path(path).name}")
        self.resize(960, 540)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._fit_preview_done = False
        if self.backend == "mpv" and self._mpv is None:
            try:
                self._mpv = mpvbackend.MpvPlayer(
                    self._ensure_mpv_host(), hwdec=hwdec, volume=volume,
                    loop=loop)
            except Exception:
                self._mpv = None
                self.backend = "qt"      # mpv 子进程拉不起来，降级 Qt 兜底
        if self.backend == "mpv" and self._mpv is not None:
            self._mpv.set_loop(loop)
            self._mpv.set_volume(volume)
            self._mpv.play(path)
            # 轮询视频分辨率，拿到后按真实比例调整窗口
            self._mpv_fit_timer = QTimer(self)
            self._mpv_fit_timer.setInterval(120)
            self._mpv_fit_timer.timeout.connect(
                lambda: self._fit_preview_when_ready(self._mpv.video_size))
            self._mpv_fit_timer.start()
        else:
            from PySide6.QtCore import QUrl
            self._ensure_qt_player()
            try:
                self._qt_player.videoSink().videoFrameChanged.connect(
                    self._fit_preview_once)
            except Exception:
                pass
            self._qt_player.setSource(QUrl.fromLocalFile(path))
            self._qt_audio.setVolume(volume / 100.0)
            self._qt_player.play()
        self.attached = False

    def _fit_preview_when_ready(self, size_getter):
        w, h = size_getter()
        if w > 0 and h > 0:
            if self._mpv_fit_timer:
                self._mpv_fit_timer.stop()
            self._fit_to_video(w, h)

    def _fit_preview_once(self, frame):
        """Qt 兜底：拿到第一帧后按真实视频比例缩放预览窗。"""
        if self._fit_preview_done:
            return
        self._fit_preview_done = True
        try:
            self._qt_player.videoSink().videoFrameChanged.disconnect(
                self._fit_preview_once)
        except Exception:
            pass
        size = frame.size()
        if not size or size.width() <= 0 or size.height() <= 0:
            return
        self._fit_to_video(size.width(), size.height())

    def _fit_to_video(self, vw: int, vh: int):
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen().availableGeometry()
        # 放大到不超过屏幕可用区域的 80%，且不放大超过 1.6 倍避免模糊
        scale = min(screen.width() * 0.8 / vw, screen.height() * 0.8 / vh)
        scale = max(0.2, min(scale, 1.6))
        w, h = max(1, round(vw * scale)), max(1, round(vh * scale))
        self.resize(w, h)
        self.move(screen.center().x() - w // 2, screen.center().y() - h // 2)
        self._fit_preview_done = True

    # ---------- 暂停/恢复（全屏自动暂停用） ----------
    def pause(self):
        if self.backend == "mpv":
            if self._mpv:
                self._mpv.pause()
        elif self._qt_player:
            self._qt_player.pause()

    def resume(self):
        if self.backend == "mpv":
            if self._mpv:
                self._mpv.resume()
        elif self._qt_player:
            self._qt_player.play()

    def is_playing(self) -> bool:
        try:
            if self.backend == "mpv":
                return bool(self._mpv and not self._mpv.paused)
            return bool(self._qt_player
                        and self._qt_player.playbackState() == 2)  # PlayingState
        except Exception:
            return False

    def position_ms(self) -> int:
        try:
            if self.backend == "mpv":
                return int(self._mpv.position() * 1000)
            return int(self._qt_player.position())
        except Exception:
            return 0

    def stop(self):
        if self._mpv_fit_timer:
            self._mpv_fit_timer.stop()
            self._mpv_fit_timer = None
        if self._mpv is not None:
            self._mpv.terminate()
            self._mpv = None
        if self._mpv_host:
            try:
                mpvhost.destroy(self._mpv_host)
            except Exception:
                pass
            self._mpv_host = None
        if self._qt_player is not None:
            self._qt_player.stop()
        try:
            videowall.VideoWallpaperWindow.detach(self)
        except Exception:
            pass
        self.hide()
        self.attached = False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.library = Library()
        # 代理：配置 > 系统代理自动探测
        proxy = str(self.config.get("proxy", "")).strip()
        if not proxy:
            set_proxy(autodetect_proxy())
        elif proxy.lower() == "direct":
            set_proxy("")
        else:
            set_proxy(proxy)
        self.setWindowTitle(APP_NAME_CN)
        self.resize(1024, 680)
        # 液态玻璃主窗口：无边框 + 透明背景（让 DWM 亚克力透出来）
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # 自动扫描壁纸目录（软件自带 wallpapers/ + 用户配置的 watch_folders）
        self._scan_watch_folders()

        self.thumbs = ThumbLoader(self)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("glassTabs")
        self.static_tab = StaticTab(self.library, self.thumbs)
        self.video_tab = VideoTab(self.library, self.thumbs)
        self.online_tab = OnlineTab(self.config, self.library, self.thumbs)
        self.settings_tab = SettingsTab(self.config)
        self.tabs.addTab(self.static_tab, "静态壁纸")
        self.tabs.addTab(self.video_tab, "动态壁纸")
        self.tabs.addTab(self.online_tab, "在线发现")
        self.tabs.addTab(self.settings_tab, "设置")

        # 根容器：标题栏 + 标签页，整体承载玻璃质感
        root = QWidget()
        root.setObjectName("root")
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self.title_bar = TitleBar(self)
        rl.addWidget(self.title_bar)
        rl.addWidget(self.tabs, 1)
        self.setCentralWidget(root)
        if not is_win11():
            # 非 Win11 没有亚克力背景，透明窗口会透出桌面，回退为纯色底
            root.setStyleSheet("#root { background: #1b1d26; }")

        # 状态栏
        self.statusBar().showMessage("就绪")
        for tab in (self.static_tab, self.video_tab, self.online_tab):
            tab.status.connect(self.statusBar().showMessage)

        # 信号
        self.static_tab.set_as_wallpaper.connect(self.set_image_wallpaper)
        self.static_tab.crop_request.connect(self._open_crop_dialog)
        self.video_tab.set_video.connect(self.set_video_wallpaper)
        self.video_tab.preview_video.connect(self.preview_video)
        self.video_tab.stop_video.connect(self.stop_video_wallpaper)
        self.online_tab.set_wallpaper.connect(self.set_image_wallpaper)
        self.settings_tab.changed.connect(self._on_settings_changed)

        # 轮播（SPI 设置壁纸可能阻塞数秒，整个切换放工作线程；on_change 从
        # 工作线程触发，走 bridge 队列回 GUI 线程刷状态栏）
        self.slideshow = Slideshow(
            self.config, self.library,
            on_change=lambda p: self._bridge_queue.put(
                lambda: self.statusBar().showMessage(f"已切换：{Path(p).name}")))
        self.slide_timer = QTimer(self)
        self.slide_timer.timeout.connect(self.next_wallpaper_async)
        self._apply_slideshow()

        # 视频壁纸
        self.video_window: VideoPlayerWindow | None = None
        self._fs_timer = QTimer(self)
        self._fs_timer.setInterval(2000)
        self._fs_timer.timeout.connect(self._check_fullscreen_pause)
        self._keep_timer = QTimer(self)
        self._keep_timer.setInterval(1500)
        self._keep_timer.timeout.connect(self._video_keep_alive)
        self._video_paused_by_fs = False

        # WebView2 最小化还原后偶发白屏（GPU 交换链停摆，mpv 硬解高负载时易发）：
        # 轮询检测「最小化→还原」动作，还原后轻推一次窗口尺寸强制重建交换链。
        self._wv_iconic = None
        self._wv_timer = QTimer(self)
        self._wv_timer.setInterval(1200)
        self._wv_timer.timeout.connect(self._watch_webview_window)
        self._wv_timer.start()

        # 托盘
        self._setup_tray()

        # 全局快捷键 Ctrl+Alt+N
        self._register_hotkey()

        # 标签切换淡入
        self.tabs.currentChanged.connect(self._fade_tab)

        # Web UI 桥接：Flask 线程把 GUI 操作排进队列，由 GUI 线程定时消费
        import queue as _queue
        self._bridge_queue: _queue.Queue = _queue.Queue()
        self._bridge_timer = QTimer(self)
        self._bridge_timer.setInterval(50)
        self._bridge_timer.timeout.connect(self._drain_bridge)
        self._bridge_timer.start()

    def _watch_webview_window(self):
        """检测 WebView2 窗口从最小化还原，延迟后轻推尺寸以修复白屏。"""
        # 首 tick 消费开机恢复（一次性；周期性定时器比 singleShot 可靠）
        if not getattr(self, "_restore_done", False):
            self._restore_done = True
            cur = getattr(self, "_pending_restore", "")
            self._pending_restore = ""
            if cur and Path(cur).exists():
                self.set_video_wallpaper(cur)
        if not getattr(self, "_web_mode", False):
            return
        try:
            import ctypes
            u32 = ctypes.windll.user32
            h = u32.FindWindowW(None, "MeWallpaper")
            if not h:
                return
            iconic = bool(u32.IsIconic(h))
            if self._wv_iconic and not iconic:
                QTimer.singleShot(600, self._webview_nudge)
                QTimer.singleShot(1800, self._webview_nudge)
            self._wv_iconic = iconic
        except Exception:
            pass

    def _webview_nudge(self):
        """±1px 轻推窗口尺寸，强制 WebView2 重建交换链。"""
        try:
            import ctypes
            from ctypes import wintypes
            u32 = ctypes.windll.user32
            h = u32.FindWindowW(None, "MeWallpaper")
            if not h or u32.IsIconic(h):
                return
            r = wintypes.RECT()
            u32.GetWindowRect(h, ctypes.byref(r))
            w, hh = r.right - r.left, r.bottom - r.top
            u32.SetWindowPos(h, 0, 0, 0, w + 1, hh + 1, 0x0002 | 0x0004)
            QTimer.singleShot(400, lambda: u32.SetWindowPos(
                h, 0, 0, 0, w, hh, 0x0002 | 0x0004))
        except Exception:
            pass

    def bridge_invoke(self, fn):
        """供 Web API 线程调用：把函数调度到 GUI 线程执行。"""
        from .. import flicklog
        flicklog.log(f"bridge put {getattr(fn, '__name__', fn)}")
        self._bridge_queue.put(fn)

    def _drain_bridge(self):
        while True:
            try:
                fn = self._bridge_queue.get_nowait()
            except Exception:
                break
            from .. import flicklog
            flicklog.log(f"bridge run {getattr(fn, '__name__', fn)}")
            try:
                fn()
            except Exception:
                import traceback
                flicklog.log("bridge EX\n" + traceback.format_exc())

        # 窗口图标
        icon_path = PROJECT_ROOT / "app" / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # 启动时恢复上次的壁纸
        from .. import flicklog as _fl0
        import os as _os0, traceback as _tb0
        if not hasattr(MainWindow, "_init_logged"):
            MainWindow._init_logged = True
            _fl0.log(f"MainWindow init id={id(self)} pid={_os0.getpid()}\n"
                     + "".join(_tb0.format_stack()[-6:-1]))
        cur = self.config.get("current_wallpaper", "")
        if cur and Path(cur).exists():
            if self.config.get("current_wallpaper_type") == "image":
                self.statusBar().showMessage(f"当前壁纸：{Path(cur).name}")
            else:
                # 视频壁纸恢复：只登记 pending，由 _wv_timer 首 tick 消费。
                # 不用 QTimer.singleShot：本环境实测一次性定时器会被
                # 嵌套事件循环反复触发（鬼影重挂闪屏）。
                self._pending_restore = cur

    # ---------- 设置壁纸 ----------
    def _restore_pending_wallpaper(self):
        """开机自动恢复视频壁纸（一次性消费）。"""
        cur = getattr(self, "_pending_restore", "")
        self._pending_restore = ""
        if cur and Path(cur).exists():
            self.set_video_wallpaper(cur)

    def set_image_wallpaper(self, path: str):
        from .. import flicklog
        flicklog.log("set_image enter")
        self.stop_video_wallpaper(restore=False)
        # SystemParametersInfo 在 Explorer 忙 / 视频解码负载高时会阻塞数秒，
        # 放工作线程执行，GUI 线程只回写结果，避免界面和 Web 桥接整体假死。
        import threading
        style = self.config.style

        def _work():
            ok = set_wallpaper(path, style)
            flicklog.log(f"set_image SPI ok={ok}")

            def _after():
                if ok:
                    self.config.set("current_wallpaper", str(Path(path).resolve()))
                    self.config.set("current_wallpaper_type", "image")
                    self.statusBar().showMessage(f"已设置壁纸：{Path(path).name}")
                else:
                    # 不能弹模态框：Web 模式主窗口隐藏，模态框会无声卡死 GUI 线程
                    flicklog.log(f"set_image FAILED {path}")
                    self.statusBar().showMessage(f"无法设置壁纸：{Path(path).name}")

            # 注意：工作线程没有 Qt 事件循环，QTimer.singleShot 在这里不会触发，
            # 必须走 bridge 队列由 GUI 线程消费。
            self._bridge_queue.put(_after)

        threading.Thread(target=_work, daemon=True).start()

    def set_video_wallpaper(self, path: str, force: bool = False):
        # 幂等：同一路径已挂上桌面且在播，直接忽略（除非显式强制重设）。
        # 自动恢复定时器在嵌套事件循环里可能重复触发，不能因此反复重挂；
        # 但视频选项（循环/拉伸/解码）变更需要强制重建播放器才能生效。
        vw = self.video_window
        if (not force and vw is not None and vw.attached
                and str(Path(path).resolve())
                    == self.config.get("current_wallpaper", "")):
            return
        # 重入保护：定时器可能并发触发（自动恢复 + 启动参数），
        # 弹模态框会嵌套事件循环放大重入 → 栈溢出崩溃，必须挡住
        if getattr(self, "_setting_video", False):
            return
        self._setting_video = True
        try:
            from .. import flicklog as _fl
            import traceback as _tb
            _fl.log("set_video enter\n" + "".join(_tb.format_stack()[-8:-1]))
            if self.video_window is None:
                self.video_window = VideoPlayerWindow()
            ok = self.video_window.play(
                path,
                volume=int(self.config.get("video_volume", 0)),
                stretch=bool(self.config.get("video_stretch", True)),
                hwdec=bool(self.config.get("video_hw_decode", True)),
                loop=bool(self.config.get("video_loop", True)),
                style=str(self.config.get("wallpaper_style", "fill")),
            )
            if not ok:
                # 失败常见原因是 WorkerW 尚未就绪；异步重试两轮，
                # 单实例冲突时由重入保护挡掉
                def _retry(n: int):
                    import time as _t
                    for _ in range(n):
                        _t.sleep(1.5)
                        if getattr(self, "_setting_video", True):
                            break
                        if self.video_window and not self.video_window.attached:
                            self.set_video_wallpaper(path)
                            break
                threading.Thread(target=_retry, args=(2,),
                                 daemon=True).start()
            from .. import flicklog
            flicklog.log(f"set_video ok={ok}")
            if ok:
                self.config.set("current_wallpaper", str(Path(path).resolve()))
                self.config.set("current_wallpaper_type", "video")
                self.statusBar().showMessage(f"已设置动态壁纸：{Path(path).name}")
                if self.config.get("video_paused_on_fullscreen", True):
                    self._fs_timer.start()
                self._keep_timer.start()   # 层级保活，防 Explorer 重绘盖掉
            else:
                self.statusBar().showMessage(
                    "动态壁纸失败：无法嵌入桌面层（WorkerW），已在窗口中预览")
                self.video_window.showNormal()
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self.statusBar().showMessage(f"动态壁纸失败：{ex}")
        finally:
            self._setting_video = False

    def stop_video_wallpaper(self, restore: bool = True):
        # 无条件 stop：既能停桌面视频壁纸，也能关掉浮动预览窗。
        # stop() 内部对未播放状态是安全的（hide + detach + terminate）。
        from .. import flicklog
        flicklog.log(f"stop_video restore={restore}")
        if self.video_window:
            self.video_window.stop()
        self._fs_timer.stop()
        self._keep_timer.stop()
        self._video_paused_by_fs = False

    def _video_keep_alive(self):
        """壁纸层级维护。

        关键约束：绝不能在定时器里无脑 SetWindowPos/Z-order 操作——
        flip 模型的 d3d11 交换链被踢出/拉回独立翻转平面时就是一次闪屏；
        给 Progman 反复发 0x052C 同样会引起桌面闪烁。
        只在「真的掉了」或「真的被盖到不是最底层」时才动手。
        """
        vw = self.video_window
        if not vw or not vw.attached:
            self._keep_timer.stop()
            return
        from .. import flicklog
        self._ka_ticks = getattr(self, "_ka_ticks", 0) + 1
        if self._ka_ticks % 20 == 1:
            flicklog.log("ka alive")
        if videowall.VideoWallpaperWindow.quick_check(vw):
            # 还在 WorkerW 下且可见：仅当不再是 WorkerW 最底层子窗口
            # （Explorer 重绘把图标层顶上来了）才补一次压底。
            # 压底是幂等的：成功一次后 is_bottom_child 即恢复为真，
            # 不会每个周期都操作 Z-order（那对 flip 交换链就是闪屏）。
            if videowall.VideoWallpaperWindow.is_bottom_child(vw):
                return
            try:
                flicklog.log("ka press bottom")
                user32.SetWindowPos(int(vw.winId()), 1, 0, 0, 0, 0,
                                    0x0013)  # HWND_BOTTOM | NOMOVE|NOSIZE|NOACTIVATE
            except Exception:
                pass
            return
        flicklog.log("ka reattach "
                     f"parent={user32.GetParent(int(vw.winId()))} "
                     f"lastw={videowall._last_workerw} "
                     f"vis={user32.IsWindowVisible(int(vw.winId()))}")
        try:
            flicklog.log("ka reattach do")
            videowall.VideoWallpaperWindow.attach(
                vw, stretch=bool(self.config.get("video_stretch", True)))
        except Exception:
            pass

    # ---------- 区域截图设置壁纸 ----------
    @staticmethod
    def _bring_to_front(widget):
        """把 Qt 窗口强制弹到最前：置顶→取消置顶（无需前台权限的可靠舞步）。"""
        try:
            hwnd = int(widget.winId())
            u32 = ctypes.windll.user32
            widget.show()
            widget.raise_()
            widget.activateWindow()
            u32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
            QTimer.singleShot(400, lambda: u32.SetWindowPos(
                hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040))
        except Exception:
            pass

    def _open_frame_dialog(self, path: str):
        """视频截帧：选帧 → 直接设壁纸 或 送去裁剪。"""
        from .frame_dialog import FramePickDialog
        dlg = FramePickDialog(path, self)
        dlg.set_as_wallpaper.connect(self._on_frame_set_wallpaper)
        dlg.crop_requested.connect(self._on_frame_crop)
        dlg.show()
        self._bring_to_front(dlg)
        dlg.exec()

    def _on_frame_set_wallpaper(self, png_path: str):
        self.library.add(png_path, entry_type="image", source="frame")
        self.set_image_wallpaper(png_path)

    def _on_frame_crop(self, png_path: str):
        self.library.add(png_path, entry_type="image", source="frame")
        self._open_crop_dialog(png_path)

    def _open_crop_dialog(self, path: str):
        from PySide6.QtGui import QGuiApplication
        from .crop_dialog import CropDialog
        screen = QGuiApplication.primaryScreen().geometry()
        ratio = (screen.width(), screen.height())
        dlg = CropDialog(path, ratio, self)
        dlg.set_as_wallpaper.connect(self.set_image_wallpaper)
        dlg.save_to_library.connect(self._save_crop_to_library)
        dlg.show()
        self._bring_to_front(dlg)
        dlg.exec()

    def _save_crop_to_library(self, path: str):
        self.library.add(path, source="crop")
        self.static_tab.refresh()
        self.statusBar().showMessage(f"已保存到库：{Path(path).name}")

    # ---------- 视频预览 ----------
    def preview_video(self, path: str):
        try:
            if self.video_window is None:
                self.video_window = VideoPlayerWindow()
            # 预览会临时摘下桌面壁纸；关闭预览时若之前挂着壁纸，自动恢复
            self.video_window.on_preview_closed = self._after_preview_closed
            self.video_window.preview(path,
                                      volume=int(self.config.get("video_volume", 0)),
                                      hwdec=bool(self.config.get("video_hw_decode", True)),
                                      loop=bool(self.config.get("video_loop", True)))
        except Exception as ex:
            QMessageBox.warning(self, "预览失败",
                                f"无法播放该视频：\n{ex}\n请确认系统有可用视频解码器。")

    def _after_preview_closed(self):
        """预览关闭后恢复桌面壁纸（仅当之前挂的是视频壁纸）。"""
        cur = self.config.get("current_wallpaper", "")
        if (cur and Path(cur).exists()
                and self.config.get("current_wallpaper_type") == "video"):
            self.set_video_wallpaper(cur)

    # ---------- 窗口动画 ----------
    def _fade_tab(self, index: int):
        # 只触发懒加载；不做标签页淡入（父级效果会和卡片效果嵌套导致卡片消失）
        w = self.tabs.widget(index)
        if w is self.online_tab:
            self.online_tab.ensure_loaded()

    # ---------- 自动扫描 ----------
    def _scan_watch_folders(self):
        default_wp = PROJECT_ROOT / "wallpapers"
        folders = list(self.config.get("watch_folders", []))
        if str(default_wp) not in folders and default_wp.exists():
            folders.append(str(default_wp))
        # 存储目录（在线下载位置）也纳入扫描，配合主界面「一键导入」
        dl = self.config.get("download_dir")
        if dl and Path(dl).exists() and str(Path(dl)) not in folders:
            folders.append(str(Path(dl)))
        self.config.set("watch_folders", folders)
        total = 0
        for f in folders:
            if Path(f).exists():
                total += self.library.scan_folder(f)
        if total:
            print(f"扫描壁纸目录，新增 {total} 个")


    def _check_fullscreen_pause(self):
        if not self.video_window or not self.video_window.attached:
            return
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return
        # 桌面/任务栏等系统外壳窗口的矩形就是整个屏幕，但前台是它们
        # 并不代表用户在跑全屏应用——不排除会把「桌面空闲」误判成全屏，
        # 壁纸被无限期暂停（表现为「只播了一次就停」）。
        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        if cls_buf.value in ("Progman", "WorkerW", "Shell_TrayWnd",
                             "Shell_SecondaryTrayWnd", "SysListView32"):
            return
        # 自己的 WebView2 界面窗口最大化时同样是全屏矩形，不算
        title_buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title_buf, 256)
        if title_buf.value == "MeWallpaper":
            return
        rc = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        is_full = (rc.right - rc.left >= sw and rc.bottom - rc.top >= sh
                   and hwnd != int(self.winId()))
        if is_full and not self._video_paused_by_fs:
            from .. import flicklog
            flicklog.log("fs pause")
            self.video_window.pause()
            self._video_paused_by_fs = True
        elif not is_full and self._video_paused_by_fs:
            from .. import flicklog
            flicklog.log("fs resume")
            self.video_window.resume()
            self._video_paused_by_fs = False

    # ---------- 轮播 ----------
    def next_wallpaper_async(self):
        """工作线程执行轮播切换，避免 SPI 阻塞 GUI 线程。"""
        import threading
        threading.Thread(target=self.slideshow.next_wallpaper,
                         daemon=True).start()

    def _apply_slideshow(self):
        if self.config.get("slideshow_enabled", False):
            minutes = max(1, int(self.config.get("slideshow_minutes", 30)))
            self.slide_timer.start(minutes * 60 * 1000)
        else:
            self.slide_timer.stop()

    def _on_settings_changed(self, keys=None):
        self._apply_slideshow()
        keys = keys or set()
        cur = self.config.get("current_wallpaper", "")
        if not cur or not Path(cur).exists():
            return
        ctype = self.config.get("current_wallpaper_type")
        if "wallpaper_style" in keys and ctype == "image":
            # 填充方式变了：立即用新样式重设当前壁纸，
            # 否则要等下一次换壁纸才生效，看起来像「设置不生效」
            self.set_image_wallpaper(cur)
        if ((keys & {"video_stretch", "video_hw_decode", "video_loop",
                     "wallpaper_style"})   # 填充方式对动态壁纸同样即时生效
                and ctype == "video" and self.video_window
                and self.video_window.attached):
            # force=True：同路径幂等守卫会挡住普通重设，这里必须强制重建
            self.set_video_wallpaper(cur, force=True)
        if "video_volume" in keys and ctype == "video" and self.video_window:
            vw = self.video_window
            try:
                if vw._mpv:
                    vw._mpv.set_volume(int(self.config.get("video_volume", 0)))
                elif vw._qt_audio:
                    vw._qt_audio.setVolume(
                        int(self.config.get("video_volume", 0)) / 100.0)
            except Exception:
                pass

    # ---------- 托盘 ----------
    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self)
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setBrush(QColor("#5b8def"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(2, 2, 28, 28, 6, 6)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "壁")
        painter.end()
        icon = QIcon(pm)
        self.tray.setIcon(icon)
        menu = QMenu()
        act_show = menu.addAction("打开主界面")
        act_next = menu.addAction("随机换一张 (Ctrl+Alt+N)")
        act_stop_video = menu.addAction("停止动态壁纸")
        menu.addSeparator()
        act_quit = menu.addAction("退出")
        self.tray.setContextMenu(menu)
        self.tray.show()
        self._open_ui = None   # Web UI 模式下由 __main__ 注入“打开界面”回调
        act_show.triggered.connect(self._show_ui)
        act_next.triggered.connect(self.next_wallpaper_async)
        act_stop_video.triggered.connect(self.stop_video_wallpaper)
        act_quit.triggered.connect(self._quit)
        self.tray.activated.connect(
            lambda reason: self._show_ui()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)

    def _quit(self):
        self._quitting = True
        if getattr(self, "_before_quit", None):
            self._before_quit()     # 通知 webview 层不要再重建窗口
        self.stop_video_wallpaper()
        ctypes.windll.user32.UnregisterHotKey(int(self.winId()), HOTKEY_NEXT_ID)
        if hasattr(self, "tray"):
            self.tray.hide()          # 不 hide 的话图标会驻留到鼠标扫过才消失
        QTimer.singleShot(0, self.close)
        if getattr(self, "_web_mode", False):
            # Web 模式：Qt 窗口是隐藏的，webview 阻塞在主线程；
            # 清理完成后直接结束进程（daemon 线程随主线程退出）
            import os as _os
            QTimer.singleShot(400, lambda: _os._exit(0))

    def _show_ui(self):
        """托盘「打开主界面」：Web UI 模式走回调，经典模式显示 Qt 窗口。"""
        if getattr(self, "_open_ui", None) is not None:
            self._open_ui()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    # ---------- 快捷键 ----------
    def _register_hotkey(self):
        ok = ctypes.windll.user32.RegisterHotKey(
            int(self.winId()), HOTKEY_NEXT_ID,
            MOD_CONTROL | MOD_ALT, VK_N)
        if not ok:
            self.statusBar().showMessage("快捷键注册失败（可能已被占用）")

    def showEvent(self, event):
        super().showEvent(event)
        if is_win11() and not getattr(self, "_glass_on", False):
            # 首次显示后 hwnd 才有效；启用 DWM 亚克力背景
            self._glass_on = enable_glass(int(self.winId()))

    def nativeEvent(self, event_type, message):
        if event_type == "windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam == HOTKEY_NEXT_ID:  # WM_HOTKEY
                self.next_wallpaper_async()
                return True, 0
            if msg.message == 0x0084:  # WM_NCHITTEST：无边框窗口的边框拉伸 + 标题栏
                pt = _POINT()
                if user32.GetCursorPos(ctypes.byref(pt)):
                    rc = wintypes.RECT()
                    user32.GetWindowRect(int(self.winId()), ctypes.byref(rc))
                    dpr = self.devicePixelRatioF()
                    border = max(6, int(round(7 * dpr)))
                    x, y = pt.x, pt.y
                    if not (rc.left <= x <= rc.right and rc.top <= y <= rc.bottom):
                        return super().nativeEvent(event_type, message)
                    if not self.isMaximized():
                        if y < rc.top + border:
                            if x < rc.left + border:
                                return True, 13    # HTTOPLEFT
                            if x > rc.right - border:
                                return True, 14    # HTTOPRIGHT
                            return True, 12        # HTTOP
                        if y > rc.bottom - border:
                            if x < rc.left + border:
                                return True, 16    # HTBOTTOMLEFT
                            if x > rc.right - border:
                                return True, 17    # HTBOTTOMRIGHT
                            return True, 15        # HTBOTTOM
                        if x < rc.left + border:
                            return True, 10        # HTLEFT
                        if x > rc.right - border:
                            return True, 11        # HTRIGHT
                    # 标题栏区域（右侧留给三个窗口按钮）
                    title_h = int(round(self.title_bar.height() * dpr))
                    btn_w = int(round(140 * dpr))
                    if (y < rc.top + title_h) and (x < rc.right - btn_w
                                                   or self.isMaximized()):
                        return True, 2             # HTCAPTION
                return super().nativeEvent(event_type, message)
            if msg.message == 0x0024:  # WM_GETMINMAXINFO：最大化时只覆盖工作区（不吞任务栏）
                mi = _MONITORINFO()
                mi.cbSize = ctypes.sizeof(mi)
                mon = user32.MonitorFromWindow(int(self.winId()), 2)
                if mon and user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                    mmi = ctypes.cast(msg.lParam,
                                      ctypes.POINTER(_MINMAXINFO)).contents
                    mmi.ptMaxPosition.x = mi.rcMonitor.left
                    mmi.ptMaxPosition.y = mi.rcMonitor.top
                    mmi.ptMaxSize.x = mi.rcMonitor.right - mi.rcMonitor.left
                    mmi.ptMaxSize.y = mi.rcMonitor.bottom - mi.rcMonitor.top
                    mmi.ptMinTrackSize.x = int(680 * self.devicePixelRatioF())
                    mmi.ptMinTrackSize.y = int(480 * self.devicePixelRatioF())
                    return True, 0
                return super().nativeEvent(event_type, message)
        return super().nativeEvent(event_type, message)

    # ---------- 关闭行为 ----------
    def closeEvent(self, e: QCloseEvent):
        if getattr(self, "_quitting", False):
            if hasattr(self, "tray"):
                self.tray.hide()
            e.accept()
            return
        if hasattr(self, "tray"):
            e.ignore()
            self.hide()
            self.tray.showMessage(
                APP_NAME_CN, "已最小化到托盘，双击图标可重新打开。",
                QSystemTrayIcon.MessageIcon.Information, 2000)
        else:
            self.stop_video_wallpaper()
            e.accept()
