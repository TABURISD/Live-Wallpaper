"""动态壁纸页：视频列表（带封面），双击设为动态壁纸。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..config import VIDEO_EXTS
from .grid import WallpaperCard, WallpaperGrid


class VideoTab(QWidget):
    set_video = Signal(str)       # 设为动态壁纸
    preview_video = Signal(str)   # 窗口内预览
    stop_video = Signal()
    status = Signal(str)

    def __init__(self, library, thumb_loader, parent=None):
        super().__init__(parent)
        self.library = library
        self.thumbs = thumb_loader
        self.filter_text = ""
        self._entries = {}

        bar = QHBoxLayout()
        btn_import = QPushButton("导入视频")
        btn_scan = QPushButton("扫描文件夹")
        self.search = QLineEdit()
        self.search.setPlaceholderText("按名称筛选…")
        self.count = QLabel("")
        bar.addWidget(btn_import)
        bar.addWidget(btn_scan)
        bar.addWidget(self.search, stretch=1)
        bar.addWidget(self.count)

        self.grid = WallpaperGrid()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid)

        tip = QLabel("双击封面设为动态壁纸；右键可预览或停止")
        tip.setStyleSheet("color:#888;")

        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(tip)
        lay.addWidget(scroll)

        btn_import.clicked.connect(self._import_files)
        btn_scan.clicked.connect(self._import_dir)
        self.search.textChanged.connect(self._on_search)
        self.grid.activated.connect(self._activate)
        self.grid.context.connect(self._context)
        self.thumbs.loaded.connect(self._on_thumb)

        self.refresh()

    def refresh(self):
        self.grid.clear_all()
        entries = self.library.videos()
        if self.filter_text:
            t = self.filter_text.lower()
            entries = [e for e in entries if t in e.name.lower()]
        self._entries = {e.path: e for e in entries}
        self.count.setText(f"{len(entries)} 个")
        for e in entries:
            badge = "视频壁纸" + (" ★" if e.favorite else "")
            card = WallpaperCard(e.path, e.name, badge)
            card.show_fav(e.favorite)
            card.mouseDoubleClickEvent = lambda _ev, k=e.path: self._activate(k)
            self.grid.add_card(card)
            cover = e.cover or self.library.find_cover(e.path)
            if cover:
                self.thumbs.request(e.path, "local", cover)
            else:
                card.img.setText("无封面")

    def _on_thumb(self, key, pm):
        card = self.grid._cards.get(key)
        if card and not pm.isNull():
            card.set_pixmap(pm)

    def _on_search(self, text: str):
        self.filter_text = text.strip()
        self.refresh()

    def _activate(self, key: str):
        if key in self._entries:
            self.set_video.emit(key)

    def _context(self, key: str, pos):
        e = self._entries.get(key)
        if not e:
            return
        menu = QMenu(self)
        act_set = menu.addAction("设为动态壁纸")
        act_preview = menu.addAction("预览（窗口播放）")
        act_stop = menu.addAction("停止动态壁纸")
        menu.addSeparator()
        act_open = menu.addAction("打开所在文件夹")
        act_del = menu.addAction("从库中移除")
        chosen = menu.exec(pos)
        if chosen == act_set:
            self.set_video.emit(key)
        elif chosen == act_preview:
            self.preview_video.emit(key)
        elif chosen == act_stop:
            self.stop_video.emit()
        elif chosen == act_open:
            import subprocess
            subprocess.Popen(f'explorer /select,"{e.path}"')
        elif chosen == act_del:
            self.library.remove(key)
            self.refresh()

    def _import_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择视频", "",
            "视频 (*.mp4 *.mkv *.mov *.webm *.avi *.m4v *.wmv)")
        n = 0
        for f in files:
            if Path(f).suffix.lower() in VIDEO_EXTS:
                e = self.library.add(f, entry_type="video")
                e.cover = self.library.find_cover(e.path)
                n += 1
        self.library.save()
        self.status.emit(f"已导入 {n} 个视频")
        self.refresh()

    def _import_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            n = self.library.scan_folder(folder)
            self.status.emit(f"扫描完成，新增 {n} 个")
            self.refresh()
