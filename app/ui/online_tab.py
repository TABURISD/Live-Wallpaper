"""在线壁纸页：Wallhaven / 必应每日 / Picsum 浏览、下载、直接设为壁纸。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, Signal, QThreadPool
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ..config import DOWNLOAD_DIR
from ..sources import bing, picsum, wallhaven
from .grid import WallpaperCard, WallpaperGrid


class _SearchSignals(QObject):
    done = Signal(list)
    failed = Signal(str)


class _SearchJob(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _SearchSignals()

    def run(self):
        try:
            self.signals.done.emit(self.fn(*self.args, **self.kwargs))
        except Exception as ex:
            try:
                self.signals.failed.emit(str(ex))
            except RuntimeError:
                pass   # 应用正在退出


class OnlineTab(QWidget):
    set_wallpaper = Signal(str)   # 本地图片路径
    status = Signal(str)

    SOURCES = ["Wallhaven", "必应每日", "Picsum 摄影"]

    def __init__(self, config, library, thumb_loader, parent=None):
        super().__init__(parent)
        self.config = config
        self.library = library
        self.thumbs = thumb_loader
        self.items: dict[str, dict] = {}
        self.page = 1

        bar = QHBoxLayout()
        self.source = QComboBox()
        self.source.addItems(self.SOURCES)
        self.query = QLineEdit()
        self.query.setPlaceholderText("搜索关键词（Wallhaven）…")
        self.sort = QComboBox()
        self.sort.addItems(["按收藏", "按浏览", "最新", "随机"])
        self.btn_search = QPushButton("搜索")
        self.btn_prev = QPushButton("上一页")
        self.btn_next = QPushButton("下一页")
        self.page_label = QLabel("1")
        bar.addWidget(self.source)
        bar.addWidget(self.query, stretch=1)
        bar.addWidget(self.sort)
        bar.addWidget(self.btn_search)
        bar.addWidget(self.btn_prev)
        bar.addWidget(QLabel("页"))
        bar.addWidget(self.page_label)
        bar.addWidget(self.btn_next)

        self.grid = WallpaperGrid()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid)

        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(scroll)

        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self._loaded = False

        self.btn_search.clicked.connect(lambda: self.search(1))
        self.query.returnPressed.connect(lambda: self.search(1))
        self.btn_prev.clicked.connect(lambda: self.search(self.page - 1))
        self.btn_next.clicked.connect(lambda: self.search(self.page + 1))
        self.source.currentIndexChanged.connect(lambda _i: self.search(1))
        self.sort.currentIndexChanged.connect(lambda _i: self.search(1))
        self.grid.activated.connect(self._quick_set)
        self.grid.context.connect(self._context)
        self.thumbs.loaded.connect(self._on_thumb)

    def ensure_loaded(self):
        """第一次切到本页时才发搜索请求，加快主窗口启动。"""
        if not self._loaded:
            self._loaded = True
            self.search(1)

    # ---------- 搜索 ----------
    def search(self, page: int):
        page = max(1, page)
        self.page = page
        self.page_label.setText(str(page))
        src = self.source.currentText()
        sorting = ["favorites", "views", "date_added", "random"][self.sort.currentIndex()]
        self.grid.clear_all()
        self.items.clear()
        self.status.emit("加载中…")
        if src == "Wallhaven":
            job = _SearchJob(
                wallhaven.search, query=self.query.text().strip(),
                categories=self.config.get("wallhaven_categories", "110"),
                purity=self.config.get("wallhaven_purity", "100"),
                sorting=sorting, ratios="16x9", page=page,
                api_key=self.config.get("wallhaven_api_key", ""))
        elif src == "必应每日":
            job = _SearchJob(bing.daily, count=8)
        else:
            job = _SearchJob(picsum.random_list, page=page, limit=24)
        job.signals.done.connect(self._on_results)
        job.signals.failed.connect(lambda msg: self.status.emit(f"加载失败：{msg}"))
        self.pool.start(job)

    def _on_results(self, items: list[dict]):
        if not items:
            self.status.emit("没有结果")
            return
        for it in items:
            key = f"{it['id']}"
            self.items[key] = it
            res = it.get("resolution", "")
            fav = it.get("favorites")
            badge = f"{res} ★{fav}" if fav else res
            card = WallpaperCard(key, it.get("title") or key, badge)
            self.grid.add_card(card)
            self.thumbs.request(key, "url", it["thumb"])
        self.status.emit(f"共 {len(items)} 条结果")

    def _on_thumb(self, key, pm):
        card = self.grid._cards.get(key)
        if card and not pm.isNull():
            card.set_pixmap(pm)

    # ---------- 下载 ----------
    def _download(self, key: str) -> str | None:
        it = self.items.get(key)
        if not it:
            return None
        import hashlib, requests
        h = hashlib.md5(it["path"].encode()).hexdigest()[:10]
        ext = ".jpg"
        url_lower = it["path"].lower()
        for e in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            if e in url_lower.split("?")[0][-8:]:
                ext = ".png" if e == ".png" else e
                break
        dest = DOWNLOAD_DIR / f"{it['id']}-{h}{ext}"
        if dest.exists():
            return str(dest)
        try:
            self.status.emit("下载中…")
            from ..sources import get_proxies
            r = requests.get(it["path"], timeout=60,
                             headers={"User-Agent": "MeWallpaper/0.1"},
                             proxies=get_proxies())
            r.raise_for_status()
            dest.write_bytes(r.content)
            src = {"Wallhaven": "wallhaven", "必应每日": "bing"}.get(
                self.source.currentText(), "picsum")
            self.library.add(str(dest), source=src, title=it.get("title", ""),
                             tags=it.get("tags", []))
            self.status.emit(f"已下载 {dest.name}")
            return str(dest)
        except Exception as ex:
            self.status.emit(f"下载失败：{ex}")
            return None

    def _quick_set(self, key: str):
        path = self._download(key)
        if path:
            self.set_wallpaper.emit(path)

    def _context(self, key: str, pos):
        menu = QMenu(self)
        act_dl = menu.addAction("下载到本地库")
        act_set = menu.addAction("下载并设为壁纸")
        act_open = menu.addAction("在来源网站打开")
        chosen = menu.exec(pos)
        if chosen == act_dl:
            self._download(key)
        elif chosen == act_set:
            self._quick_set(key)
        elif chosen == act_open:
            it = self.items.get(key)
            if it and it.get("url"):
                import webbrowser
                webbrowser.open(it["url"])
