"""静态壁纸页：双击直接设置；右键支持区域截图设置。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..config import IMAGE_EXTS
from .grid import WallpaperCard, WallpaperGrid


class StaticTab(QWidget):
    set_as_wallpaper = Signal(str)   # path
    crop_request = Signal(str)       # path → 打开区域截图
    status = Signal(str)

    def __init__(self, library, thumb_loader, parent=None):
        super().__init__(parent)
        self.library = library
        self.thumbs = thumb_loader
        self.filter_text = ""
        self.filter_kind = "all"       # all | favorite
        self._entries = {}

        bar = QHBoxLayout()
        btn_import_file = QPushButton("导入图片")
        btn_import_dir = QPushButton("扫描文件夹")
        self.kind = QComboBox()
        self.kind.addItems(["全部", "仅收藏"])
        self.search = QLineEdit()
        self.search.setPlaceholderText("按名称/标签筛选…")
        self.count = QLabel("")
        bar.addWidget(btn_import_file)
        bar.addWidget(btn_import_dir)
        bar.addWidget(self.kind)
        bar.addWidget(self.search, stretch=1)
        bar.addWidget(self.count)

        self.grid = WallpaperGrid()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid)

        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(scroll)

        btn_import_file.clicked.connect(self._import_files)
        btn_import_dir.clicked.connect(self._import_dir)
        self.kind.currentIndexChanged.connect(
            lambda i: self._set_kind("favorite" if i == 1 else "all"))
        self.search.textChanged.connect(self._on_search)
        self.grid.activated.connect(self._activate)
        self.grid.context.connect(self._context)
        self.thumbs.loaded.connect(self._on_thumb)

        self.refresh()

    # ---------- 数据 ----------
    def refresh(self):
        self.grid.clear_all()
        entries = self.library.images()
        if self.filter_kind == "favorite":
            entries = [e for e in entries if e.favorite]
        if self.filter_text:
            t = self.filter_text.lower()
            entries = [e for e in entries
                       if t in e.name.lower() or any(t in x.lower() for x in e.tags)]
        self._entries = {e.path: e for e in entries}
        self.count.setText(f"{len(entries)} 张")
        for e in entries:
            card = WallpaperCard(e.path, e.name, "★ 收藏" if e.favorite else "")
            card.show_fav(e.favorite)
            card.mouseDoubleClickEvent = lambda _ev, k=e.path: self._activate(k)
            self.grid.add_card(card)
            # 原图路径交给工作线程解码缩放，避免主线程卡顿
            self.thumbs.request(e.path, "local", e.path)

    def _on_thumb(self, key, pm):
        card = self.grid._cards.get(key)
        if card and not pm.isNull():
            card.set_pixmap(pm)

    def _set_kind(self, kind: str):
        self.filter_kind = kind
        self.refresh()

    def _on_search(self, text: str):
        self.filter_text = text.strip()
        self.refresh()

    # ---------- 交互 ----------
    def _activate(self, key: str):
        if key in self._entries:
            self.set_as_wallpaper.emit(key)

    def _context(self, key: str, pos):
        e = self._entries.get(key)
        if not e:
            return
        menu = QMenu(self)
        act_set = menu.addAction("设为壁纸")
        act_crop = menu.addAction("区域截图设置壁纸…")
        act_fav = menu.addAction("取消收藏" if e.favorite else "收藏")
        act_tag = menu.addAction("编辑标签…")
        act_name = menu.addAction("重命名…")
        menu.addSeparator()
        act_open = menu.addAction("打开所在文件夹")
        act_del = menu.addAction("从库中移除")
        act_del_file = menu.addAction("从库移除并删除文件")
        chosen = menu.exec(pos)
        if chosen == act_set:
            self.set_as_wallpaper.emit(key)
        elif chosen == act_crop:
            self.crop_request.emit(key)
        elif chosen == act_fav:
            self.library.toggle_favorite(key)
            self.refresh()
        elif chosen == act_tag:
            text, ok = QInputDialog.getText(
                self, "编辑标签", "用逗号分隔：", text=",".join(e.tags))
            if ok:
                self.library.set_tags(key, [t.strip() for t in text.split(",") if t.strip()])
                self.refresh()
        elif chosen == act_name:
            text, ok = QInputDialog.getText(self, "重命名", "标题：", text=e.name)
            if ok and text.strip():
                self.library.set_title(key, text.strip())
                self.refresh()
        elif chosen == act_open:
            import subprocess
            subprocess.Popen(f'explorer /select,"{e.path}"')
        elif chosen == act_del:
            self.library.remove(key)
            self.refresh()
        elif chosen == act_del_file:
            if QMessageBox.question(self, "确认", f"删除文件？\n{e.path}") == QMessageBox.StandardButton.Yes:
                self.library.remove(key, delete_file=True)
                self.refresh()

    # ---------- 导入 ----------
    def _import_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "", "图片 (*.jpg *.jpeg *.png *.bmp *.webp *.gif)")
        n = 0
        for f in files:
            if Path(f).suffix.lower() in IMAGE_EXTS:
                self.library.add(f, entry_type="image")
                n += 1
        self.status.emit(f"已导入 {n} 张图片")
        self.refresh()

    def _import_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            n = self.library.scan_folder(folder)
            self.status.emit(f"扫描完成，新增 {n} 个")
            self.refresh()
