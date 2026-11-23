"""缩略图与网络图片的异步加载。

- 线程内用 QImageReader 直接解码缩放（不加载原图全尺寸，大图也快）
- 网络图片在线程内下载+解码
- 信号把 QImage 带回 GUI 线程转 QPixmap
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, Signal, QThreadPool
from PySide6.QtGui import QImage, QImageReader, QPixmap


class _Signals(QObject):
    done = Signal(str, QImage)  # key, image


class _LoadJob(QRunnable):
    def __init__(self, key: str, kind: str, payload: str, target: QSize):
        super().__init__()
        self.key = key
        self.kind = kind  # local | url
        self.payload = payload
        self.target = target
        self.signals = _Signals()

    def run(self):
        img = QImage()
        try:
            if self.kind == "local":
                reader = QImageReader(self.payload)
                reader.setAutoTransform(True)
                reader.setScaledSize(self.target)   # 解码时直接缩到目标尺寸
                img = reader.read()
            else:
                import requests
                from app.sources import get_proxies
                r = requests.get(self.payload, timeout=15,
                                 headers={"User-Agent": "MeWallpaper/0.1"},
                                 proxies=get_proxies())
                r.raise_for_status()
                img.loadFromData(r.content)
                if not img.isNull() and max(img.width(), img.height()) > max(self.target.width(), self.target.height()):
                    img = img.scaled(
                        self.target, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
        except Exception:
            img = QImage()
        try:
            self.signals.done.emit(self.key, img)
        except RuntimeError:
            pass   # 应用正在退出，接收端已销毁


class ThumbLoader(QObject):
    """带内存缓存的缩略图加载器（解码全在工作线程）。"""

    loaded = Signal(str, QPixmap)

    def __init__(self, parent=None, max_side: int = 480):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self._cache: dict[str, QPixmap] = {}
        self._pending: set[str] = set()
        self._jobs: set = set()
        self.max_side = max_side

    def request(self, key: str, kind: str, payload: str):
        if key in self._cache:
            self.loaded.emit(key, self._cache[key])
            return
        if key in self._pending:
            return
        self._pending.add(key)
        job = _LoadJob(key, kind, payload, QSize(self.max_side, self.max_side))
        job.signals.done.connect(self._on_done)
        self._jobs.add(job)   # 保活
        self.pool.start(job)

    def _on_done(self, key: str, img: QImage):
        self._pending.discard(key)
        if img.isNull():
            return
        pm = QPixmap.fromImage(img)
        self._cache[key] = pm
        try:
            self.loaded.emit(key, pm)
        except RuntimeError:
            pass   # 应用正在退出
