"""区域截图设置壁纸：打开图片，框选一块区域，设为新壁纸。

支持自由比例 / 16:9 / 4:3 / 屏幕比例。裁剪结果另存到 data/crops/ 再设置。
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QScrollArea,
    QVBoxLayout, QWidget,
)

from ..config import DATA_DIR

CROP_DIR = DATA_DIR / "crops"


class CropCanvas(QLabel):
    """显示缩放后的图片并支持拖拽框选。"""

    region_changed = Signal(QRect)   # 原图坐标系中的选区

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self._orig = QPixmap(image_path)
        self.setPixmap(self._orig)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.ratio: tuple[int, int] | None = None  # (w, h)
        self._anchor: QPoint | None = None
        self._rect = QRect()      # 显示坐标
        self._zoom = 1.0

    def set_ratio(self, w: int | None, h: int | None = None):
        self.ratio = (w, h) if w else None
        if self._rect.width() > 4 and self._rect.height() > 4:
            self._apply_ratio(self._rect)
            self.update()
            self._emit()

    def _apply_ratio(self, r: QRect) -> QRect:
        if not self.ratio:
            return r
        rw, rh = self.ratio
        w, h = r.width(), r.height()
        if w * rh > h * rw:      # 太宽，削宽
            w = int(h * rw / rh)
        else:                    # 太高，削高
            h = int(w * rh / rw)
        out = QRect(r.x(), r.y(), w, h)
        out.moveCenter(r.center())
        return out.intersected(self.pixmap().rect())

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._anchor = e.position().toPoint()
            self._rect = QRect(self._anchor, QSize(0, 0))
            self.update()

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._anchor is None:
            return
        self._rect = QRect(self._anchor, e.position().toPoint()).normalized()
        self._rect = self._apply_ratio(self._rect)
        self.update()
        self._emit()

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._rect.width() < 8 or self._rect.height() < 8:
                self._rect = QRect()
                self.update()
                self._emit()
            self._anchor = None

    def _emit(self):
        self.region_changed.emit(self._rect)

    def paintEvent(self, e: QPaintEvent):
        super().paintEvent(e)
        if not self._rect.isNull() and self._rect.width() > 1:
            p = QPainter(self)
            p.setPen(Qt.GlobalColor.red)
            p.drawRect(self._rect)
            p.end()

    def crop_and_save(self) -> str | None:
        if self._rect.width() < 8:
            return None
        CROP_DIR.mkdir(parents=True, exist_ok=True)
        out = CROP_DIR / f"crop-{int(time.time() * 1000)}.jpg"
        img = self._orig.copy(self._rect)
        if img.save(str(out), "JPEG", quality=92):
            return str(out)
        return None


class CropDialog(QDialog):
    """框选后点「设为壁纸」或「保存到库」。"""

    set_as_wallpaper = Signal(str)   # 裁剪后的文件路径
    save_to_library = Signal(str)

    RATIOS = [("自由框选", None, None), ("16 : 9", 16, 9), ("9 : 16", 9, 16),
              ("4 : 3", 4, 3), ("屏幕比例", -1, -1)]

    def __init__(self, image_path: str, screen_ratio: tuple[int, int], parent=None):
        super().__init__(parent)
        self.setWindowTitle("区域截图设置壁纸 —— 拖拽框选区域")
        self.resize(1000, 700)
        self._screen_ratio = screen_ratio

        top = QHBoxLayout()
        top.addWidget(QLabel("宽高比："))
        self.ratio = QComboBox()
        for label, w, h in self.RATIOS:
            self.ratio.addItem(label, (w, h))
        top.addWidget(self.ratio)
        self.info = QLabel("在图片上拖拽框选区域（右键/取消退出）")
        top.addWidget(self.info, stretch=1)

        self.canvas = CropCanvas(image_path)
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)

        buttons = QDialogButtonBox()
        self.btn_set = buttons.addButton("设为壁纸", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_save = buttons.addButton("保存到库", QDialogButtonBox.ButtonRole.ActionRole)
        btn_cancel = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(scroll)
        lay.addWidget(buttons)

        self.ratio.currentIndexChanged.connect(self._on_ratio)
        self.canvas.region_changed.connect(self._on_region)
        self.btn_set.clicked.connect(self._do_set)
        self.btn_save.clicked.connect(self._do_save)
        btn_cancel.clicked.connect(self.reject)
        self.canvas.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.canvas.customContextMenuRequested.connect(lambda _p: self.reject())

        self._on_ratio(0)

    def _on_ratio(self, i: int):
        w, h = self.ratio.itemData(i)
        if w == -1:  # 屏幕比例
            w, h = self._screen_ratio
        self.canvas.set_ratio(w if w and w > 0 else None, h)

    def _on_region(self, r: QRect):
        if r.width() > 8:
            self.info.setText(f"已选区域：{r.width()} × {r.height()} 像素")
            self.btn_set.setEnabled(True)
            self.btn_save.setEnabled(True)
        else:
            self.info.setText("在图片上拖拽框选区域")
            self.btn_set.setEnabled(False)
            self.btn_save.setEnabled(False)

    def _crop(self) -> str | None:
        path = self.canvas.crop_and_save()
        if not path:
            self.info.setText("请先框选区域")
        return path

    def _do_set(self):
        path = self._crop()
        if path:
            self.set_as_wallpaper.emit(path)
            self.accept()

    def _do_save(self):
        path = self._crop()
        if path:
            self.save_to_library.emit(path)
            self.info.setText("已保存到库，可继续框选或关闭")
