"""界面动效辅助：淡入、阴影呼吸等。"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QTimer, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsOpacityEffect


def fade_in(widget, duration: int = 200, delay: int = 0) -> QPropertyAnimation | None:
    """控件透明度 0 -> 1 淡入，结束后自动摘除效果。

    必须摘除：QGraphicsEffect 不允许嵌套（父窗口和卡片同时挂效果会导致卡片渲染消失）。
    """
    try:
        eff = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(eff)
        an = QPropertyAnimation(eff, b"opacity", widget)
        an.setStartValue(0.0)
        an.setEndValue(1.0)
        an.setDuration(duration)
        an.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _cleanup():
            try:
                # 只有效果还是我们自己的才摘除（可能已被悬停阴影替换）
                if widget.graphicsEffect() is eff:
                    widget.setGraphicsEffect(None)
            except RuntimeError:
                pass

        an.finished.connect(_cleanup)
        widget.setProperty("_fade_anim", an)   # 保活
        if delay > 0:
            QTimer.singleShot(delay, an.start)
        else:
            an.start()
        return an
    except RuntimeError:
        return None


def lift_shadow(widget, radius: int = 22, alpha: int = 90):
    """悬浮阴影（返回 effect，挂到控件上防回收）。"""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(radius)
    eff.setOffset(0, 6)
    from PySide6.QtGui import QColor
    eff.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(eff)
    widget.setProperty("_shadow", eff)
    return eff


def clear_shadow(widget):
    widget.setGraphicsEffect(None)
