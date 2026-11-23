"""视频截帧：mpv 独立进程渲染预览 + 进度条选帧。

与动态壁纸同一个机制：mpv.exe 作为子进程渲染进纯 Win32 STATIC 宿主窗口
（Qt QWidget 会被自己的后备存储盖住 mpv 的画面，实测全黑），控制走命名
管道 IPC。取帧用 mpv 的 screenshot-to-file（原视频分辨率），不再读 OpenGL
帧缓冲——libmpv 进程内嵌入会触发官方构建 LuaJIT 的 SEH 崩溃（0xe24c4a02）。
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QSlider, QVBoxLayout, QWidget)

from .. import mpvbackend
from .. import mpvhost
from ..config import CACHE_DIR


class _MpvHost(QWidget):
    """承载 mpv 子进程画面的控件：内部铺一个纯 Win32 STATIC 子窗口。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # 禁止 Qt 擦除背景，避免重绘时底色盖住 mpv 的交换链
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._host: int | None = None
        self._player: mpvbackend.MpvPlayer | None = None
        self.ready = False
        self.fail_msg = ""

    def ensure_host(self) -> int:
        if not self._host:
            self._host = mpvhost.create(int(self.winId()))
        self._sync()
        return self._host

    def _sync(self):
        if self._host:
            try:
                dpr = self.devicePixelRatioF()
                mpvhost.sync(self._host, 0, 0,
                             int(self.width() * dpr), int(self.height() * dpr))
            except Exception:
                pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync()

    def open(self, path: str):
        try:
            wid = self.ensure_host()
            if self._player is None:
                self._player = mpvbackend.MpvPlayer(
                    wid, hwdec=True, volume=0, loop=False,
                    extra_args=("--pause",))
            self._player.play(path)
            self.ready = True
        except Exception as e:
            self.ready = False
            self.fail_msg = str(e)

    def shutdown(self):
        if self._player is not None:
            try:
                self._player.terminate()
            except Exception:
                pass
            self._player = None
        if self._host:
            try:
                mpvhost.destroy(self._host)
            except Exception:
                pass
            self._host = None
        self.ready = False

    def grab(self, out_path: str) -> bool:
        """把当前画面帧写入 out_path（原视频分辨率）。"""
        if self._player is None:
            return False
        return self._player.screenshot(out_path)


class FramePickDialog(QDialog):
    """选帧对话框。确定后通过信号把帧 PNG 路径交出去。"""

    set_as_wallpaper = Signal(str)   # 帧 PNG 路径，直接设为静态壁纸
    crop_requested = Signal(str)     # 帧 PNG 路径，送去区域裁剪

    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"视频截帧 —— {Path(video_path).name}")
        self.resize(820, 600)
        self._duration = 0.0

        self.gl = _MpvHost()
        self.gl.open(video_path)

        self.time = QLabel("00:00 / 00:00")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setEnabled(False)
        self.info = QLabel("拖动进度条选择画面，然后截取")
        self.info.setStyleSheet("color:#8b93a7;font-size:12px;")

        buttons = QDialogButtonBox()
        self.btn_set = buttons.addButton(
            "设此帧为壁纸", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_crop = buttons.addButton(
            "截取并裁剪…", QDialogButtonBox.ButtonRole.ActionRole)
        btn_cancel = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.btn_set.setEnabled(False)
        self.btn_crop.setEnabled(False)
        self.btn_set.setDefault(True)   # 回车即「设此帧为壁纸」

        lay = QVBoxLayout(self)
        lay.addWidget(self.gl, stretch=1)
        row = QHBoxLayout()
        row.addWidget(self.time)
        row.addWidget(self.slider, stretch=1)
        lay.addLayout(row)
        lay.addWidget(self.info)
        lay.addWidget(buttons)

        # 位置/时长轮询（IPC 查询，本地管道毫秒级）
        self._poll = QTimer(self)
        self._poll.setInterval(300)
        self._poll.timeout.connect(self._poll_state)
        self._poll.start()

        self.slider.sliderReleased.connect(self._seek_to_slider)
        self.btn_set.clicked.connect(lambda: self._grab(self.set_as_wallpaper))
        self.btn_crop.clicked.connect(lambda: self._grab(self.crop_requested))
        btn_cancel.clicked.connect(self.reject)

        # 渲染未就绪提示
        QTimer.singleShot(1500, self._check_ready)

    # ---------- 轮询播放状态（GUI 线程） ----------
    def _poll_state(self):
        p = self.gl._player
        if p is None:
            return
        dur = p.duration()
        pos = p.position()
        if dur > 0 and self._duration <= 0:
            self._duration = dur
            self.slider.setRange(0, int(dur * 1000))
            self.slider.setEnabled(True)
            self.btn_set.setEnabled(True)
            self.btn_crop.setEnabled(True)
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(int(pos * 1000))
            self.slider.blockSignals(False)
        self._update_time()

    def _check_ready(self):
        if not self.gl.ready:
            self.info.setText("mpv 初始化失败：" +
                              (self.gl.fail_msg or "未知错误"))

    # ---------- 关闭清理 ----------
    def _cleanup(self):
        try:
            self._poll.stop()
        except Exception:
            pass
        try:
            self.gl.shutdown()
        except Exception:
            pass

    def closeEvent(self, e):
        self._cleanup()
        super().closeEvent(e)

    def reject(self):
        self._cleanup()
        super().reject()

    # ---------- UI 更新（GUI 线程） ----------
    def _update_time(self):
        def fmt(sec: float) -> str:
            s = max(0, int(sec))
            return f"{s // 60:02d}:{s % 60:02d}"
        pos = self.slider.value() / 1000.0
        self.time.setText(f"{fmt(pos)} / {fmt(self._duration)}")

    # ---------- 选帧与取帧 ----------
    def _seek_to_slider(self):
        p = self.gl._player
        if p is None:
            return
        p.seek(self.slider.value() / 1000.0)
        self._update_time()

    def _grab(self, sig: Signal):
        if self.gl._player is None or not self.gl.ready:
            self.info.setText("mpv 还没就绪，稍等再试")
            return
        # seek 后等解码器稳定再抓帧
        QTimer.singleShot(300, lambda: self._grab_now(sig))

    def _grab_now(self, sig: Signal):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out = CACHE_DIR / f"frame-{int(time.time() * 1000)}.png"
        if self.gl.grab(str(out)):
            sig.emit(str(out))
            self.accept()
        else:
            self.info.setText("抓取画面失败，请重试")

    def accept(self):
        self._cleanup()
        super().accept()
