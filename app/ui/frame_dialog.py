"""视频截帧：mpv (libmpv) OpenGL 渲染预览 + 进度条选帧。

QMediaPlayer/WMF 在本机不可靠（预览黑屏、偶发 0xc0000409 崩溃、界面卡死），
改用与动态壁纸同一个 mpv 内核：d3d11va 硬解已在动态壁纸上验证过。
预览始终处于暂停态，拖动进度条即精准 seek；取帧直接读当前 OpenGL 帧缓冲，
不依赖 vo 的 screenshot 支持。
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QSlider, QVBoxLayout)

from .. import mpvbackend
from ..config import CACHE_DIR


class _MpvGL(QOpenGLWidget):
    """libmpv 的 OpenGL 渲染画布（vo=libmpv）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ready = False
        self.fail_msg = ""
        self._ctx = None
        self._m = None
        self._pending = None
        self._proc_cb = None
        self._ratio = self.devicePixelRatioF()

    def open(self, path: str):
        mpvbackend.backend_available()  # 确保 DLL 目录已加入搜索路径
        import mpv
        self._m = mpv.MPV(
            vo="libmpv",
            mute=True,
            pause=True,
            loop="no",
            ytdl="no",
            keep_open="yes",
            really_quiet="",
            **{"hwdec": "auto-safe", "osd-level": "0"})
        self._pending = str(path)
        # 渲染上下文（OpenGL）就绪后才能加载，否则 libmpv VO 初始化失败、
        # 播放直接中止（表现为时长始终为 0、画面全黑）
        if self.ready:
            self._start()

    def _start(self):
        if self._m is None or not self._pending:
            return
        path, self._pending = self._pending, None
        try:
            self._m.play(path)
        except Exception:
            pass

    def initializeGL(self):
        if self._m is None:
            return
        try:
            import mpv
            # get_proc_address 字段是 CFUNCTYPE，需手动包装并保持引用
            self._proc_cb = mpv.MpvGlGetProcAddressFn(self._proc)
            self._ctx = mpv.MpvRenderContext(
                self._m, "opengl",
                opengl_init_params={"get_proc_address": self._proc_cb})
            # mpv 有新帧时请求 Qt 重绘
            self._ctx.update_cb = self.update
            self.ready = True
            self._start()
        except Exception as ex:  # 渲染失败时提示
            self.ready = False
            self.fail_msg = str(ex)

    def _proc(self, _ctx, name):
        ctx = self.context()
        if ctx is None:
            return None
        if isinstance(name, bytes):
            name = name.decode("utf-8", "ignore")
        addr = ctx.getProcAddress(name)
        try:
            return int(addr) if addr else None
        except Exception:
            return None

    def resizeGL(self, w, h):
        self._ratio = self.devicePixelRatioF()
        self.update()

    def paintGL(self):
        if not self._ctx:
            return
        try:
            self._ctx.render(
                flip_y=True,
                opengl_fbo={"w": int(self.width() * self._ratio),
                            "h": int(self.height() * self._ratio),
                            "fbo": self.defaultFramebufferObject()})
            self._ctx.report_swap()
        except Exception:
            pass

    def shutdown(self):
        try:
            if self._ctx:
                self._ctx.free()
        except Exception:
            pass
        self._ctx = None
        try:
            if self._m:
                self._m.terminate()
        except Exception:
            pass
        self._m = None
        self.ready = False


class FramePickDialog(QDialog):
    """选帧对话框。确定后通过信号把帧 PNG 路径交出去。"""

    set_as_wallpaper = Signal(str)   # 帧 PNG 路径，直接设为静态壁纸
    crop_requested = Signal(str)     # 帧 PNG 路径，送去区域裁剪

    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"视频截帧 —— {Path(video_path).name}")
        self.resize(820, 600)
        self._duration = 0.0

        self.gl = _MpvGL()
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

        # 位置/时长轮询（直接读属性，比 observe_property 更稳）
        self._m = self.gl._m
        self._poll = QTimer(self)
        self._poll.setInterval(300)
        self._poll.timeout.connect(self._poll_state)
        self._poll.start()

        self.slider.sliderReleased.connect(self._seek_to_slider)
        self.btn_set.clicked.connect(lambda: self._grab(self.set_as_wallpaper))
        self.btn_crop.clicked.connect(lambda: self._grab(self.crop_requested))
        btn_cancel.clicked.connect(self.reject)

        # 渲染未就绪提示
        QTimer.singleShot(1200, self._check_ready)

    # ---------- 轮询播放状态（GUI 线程） ----------
    def _poll_state(self):
        if self._m is None:
            return
        try:
            dur = float(self._m.duration or 0)
            pos = float(self._m.time_pos or 0)
        except Exception:
            return
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
            self.info.setText("mpv 渲染初始化失败：" +
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
    def _on_duration(self, d: float):
        if d > 0 and self._duration <= 0:
            self._duration = d
            self.slider.setRange(0, int(d * 1000))
            self.slider.setEnabled(True)
            self.btn_set.setEnabled(True)
            self.btn_crop.setEnabled(True)
        self._update_time()

    def _on_pos(self, p: float):
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(int(p * 1000))
            self.slider.blockSignals(False)
        self._update_time()

    def _update_time(self):
        def fmt(sec: float) -> str:
            s = max(0, int(sec))
            return f"{s // 60:02d}:{s % 60:02d}"
        pos = self.slider.value() / 1000.0
        self.time.setText(f"{fmt(pos)} / {fmt(self._duration)}")

    # ---------- 选帧与取帧 ----------
    def _seek_to_slider(self):
        if self._m is None:
            return
        sec = self.slider.value() / 1000.0
        try:
            self._m.seek(str(sec), "absolute", "exact")
        except Exception:
            pass
        self._update_time()

    def _grab(self, sig: Signal):
        if self.gl._m is None or not self.gl.ready:
            self.info.setText("渲染还没就绪，稍等再试")
            return
        # seek 后等解码器稳定再抓帧
        QTimer.singleShot(260, lambda: self._grab_now(sig))

    def _grab_now(self, sig: Signal):
        self.gl.makeCurrent()
        img: QImage = self.gl.grabFramebuffer()
        if img.isNull():
            self.info.setText("抓取画面失败，请重试")
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out = CACHE_DIR / f"frame-{int(time.time() * 1000)}.png"
        if img.save(str(out), "PNG"):
            sig.emit(str(out))
            self.accept()
        else:
            self.info.setText("保存帧失败，请重试")

    def accept(self):
        self._cleanup()
        super().accept()
