"""壁纸网格控件：圆角卡片、悬停浮起阴影、批量淡入。"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QGridLayout, QLabel, QMenu,
    QVBoxLayout, QWidget,
)

from .anim import fade_in
from .theme import ACCENT

CARD_W, CARD_H, IMG_H = 208, 172, 128


def rounded_pixmap(pm: QPixmap, radius: int = 10, top_only: bool = True) -> QPixmap:
    """给缩略图画圆角蒙版。top_only 时只圆上角（卡片上半部分）。"""
    if pm.isNull():
        return pm
    out = QPixmap(pm.size())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    w, h = pm.width(), pm.height()
    if top_only:
        path.moveTo(0, h)
        path.lineTo(0, radius)
        path.arcTo(0, 0, radius * 2, radius * 2, 180, -90)
        path.lineTo(w - radius, 0)
        path.arcTo(w - radius * 2, 0, radius * 2, radius * 2, 90, -90)
        path.lineTo(w, h)
        path.closeSubpath()
    else:
        path.addRoundedRect(QRect(0, 0, w, h), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out


class WallpaperCard(QFrame):
    """壁纸卡片：上图下文，悬停浮起。"""

    def __init__(self, key: str, title: str = "", badge: str = "", parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("card")
        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 图片区（带顶部圆角 + 收藏角标叠放）
        self.img_wrap = QWidget()
        self.img_wrap.setObjectName("cardImgWrap")
        self.img_wrap.setFixedHeight(IMG_H)
        wrap_lay = QVBoxLayout(self.img_wrap)
        wrap_lay.setContentsMargins(0, 0, 0, 0)
        self.img = QLabel("加载中…")
        self.img.setObjectName("cardImg")
        self.img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wrap_lay.addWidget(self.img)
        self.fav_tag = QLabel("★")
        self.fav_tag.setObjectName("cardFav")
        self.fav_tag.setFixedHeight(20)
        self.fav_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fav_tag.setGeometry(0, 0, 0, 0)
        self.fav_tag.hide()
        lay.addWidget(self.img_wrap)

        # 文字区
        text = QWidget()
        text.setStyleSheet("background:transparent;")
        tl = QVBoxLayout(text)
        tl.setContentsMargins(10, 6, 10, 4)
        tl.setSpacing(0)
        self.title = QLabel(title[:22])
        self.title.setObjectName("cardTitle")
        self.badge = QLabel(badge)
        self.badge.setObjectName("cardBadge")
        tl.addWidget(self.title)
        tl.addWidget(self.badge)
        tl.addStretch(1)
        lay.addWidget(text)

    def set_pixmap(self, pm: QPixmap):
        if pm.isNull():
            return
        scaled = pm.scaled(
            self.img.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation)
        self.img.setPixmap(rounded_pixmap(scaled))

    def show_fav(self, on: bool):
        if on:
            # 叠放到图片左上角
            self.fav_tag.setParent(self.img)
            self.fav_tag.move(8, 8)
            self.fav_tag.adjustSize()
            self.fav_tag.show()
            self.fav_tag.raise_()
        else:
            self.fav_tag.hide()

    # ---------- 悬停动效 ----------
    def enterEvent(self, event):
        # 只加阴影，不换样式表（换样式表会导致整卡重绘，视觉上像“消失了”）
        eff = QGraphicsDropShadowEffect(self)
        eff.setBlurRadius(24)
        eff.setOffset(0, 7)
        eff.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(eff)
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setGraphicsEffect(None)
        self._hover = False
        self.update()
        super().leaveEvent(event)


class WallpaperGrid(QWidget):
    """支持右键菜单、双击、批量交错淡入的网格。"""

    activated = Signal(str)          # 双击/回车
    context = Signal(str, object)    # 右键 (key, global_pos)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys: list[str] = []
        self._cards: dict[str, WallpaperCard] = {}
        self._cols = 4
        self.grid = QGridLayout(self)
        self.grid.setSpacing(14)
        self.grid.setContentsMargins(14, 14, 14, 14)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    def set_columns(self, n: int):
        self._cols = max(1, n)

    def clear_all(self):
        for card in self._cards.values():
            card.deleteLater()
        self._cards.clear()
        self._keys.clear()
        while self.grid.count():
            self.grid.takeAt(0)

    def add_card(self, card: WallpaperCard, fade: bool = True):
        idx = len(self._keys)
        self._keys.append(card.key)
        self._cards[card.key] = card
        self.grid.addWidget(card, idx // self._cols, idx % self._cols,
                            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        if fade:
            fade_in(card, duration=220, delay=min(idx, 24) * 30)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        w = max(self.width(), 200)
        cols = max(2, w // (CARD_W + 18))
        if cols != self._cols:
            self._cols = cols
            while self.grid.count():
                self.grid.takeAt(0)
            for i, key in enumerate(self._keys):
                self.grid.addWidget(self._cards[key], i // cols, i % cols,
                                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
