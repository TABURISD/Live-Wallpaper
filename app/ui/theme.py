"""全局液态玻璃主题（半透明层叠 + 亚克力由 DWM 提供）。"""

ACCENT = "#5b8def"
ACCENT_SOFT = "#7aa2f7"

# 玻璃层级：主背景透光较多，卡片用白色低透明度叠加制造磨砂层次
GLASS_ROOT = "rgba(26, 28, 36, 205)"
GLASS_PANEL = "rgba(255, 255, 255, 14)"
GLASS_CARD = "rgba(255, 255, 255, 18)"
GLASS_BORDER = "rgba(255, 255, 255, 42)"
GLASS_HOVER = "rgba(255, 255, 255, 34)"

QSS = f"""
* {{
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
    outline: none;
}}

QWidget {{
    background: transparent;
    color: #e8eaf1;
}}

/* ---------- 玻璃主窗口 ---------- */
QWidget#root {{
    background: {GLASS_ROOT};
    border: 1px solid rgba(255, 255, 255, 30);
    border-radius: 12px;
}}
QWidget#titleBar {{
    background: rgba(255, 255, 255, 6);
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
}}
QLabel#titleLabel {{
    color: #eef0f6;
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}}
QPushButton#btnMin, QPushButton#btnMax, QPushButton#btnClose {{
    background: transparent;
    border: none;
    border-radius: 6px;
    color: #c9cedb;
    font-size: 13px;
}}
QPushButton#btnMin:hover, QPushButton#btnMax:hover {{
    background: rgba(255, 255, 255, 32);
    color: #ffffff;
}}
QPushButton#btnClose:hover {{
    background: #e81123;
    color: #ffffff;
}}

/* ---------- 标签页 ---------- */
QTabWidget::pane {{
    border: none;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: #9aa0b4;
    padding: 9px 22px;
    margin-right: 4px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{
    color: #dde1ec;
}}
QTabBar::tab:selected {{
    color: #ffffff;
    border-bottom: 2px solid {ACCENT};
    font-weight: bold;
}}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: {GLASS_PANEL};
    border: 1px solid {GLASS_BORDER};
    border-radius: 8px;
    padding: 6px 16px;
    color: #e8eaf1;
}}
QPushButton:hover {{
    background: {GLASS_HOVER};
    border-color: rgba(255, 255, 255, 70);
}}
QPushButton:pressed {{
    background: rgba(255, 255, 255, 8);
}}
QPushButton:disabled {{
    color: #666c7c;
    border-color: rgba(255, 255, 255, 20);
}}

/* ---------- 输入 ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {GLASS_PANEL};
    border: 1px solid {GLASS_BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    color: #e8eaf1;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: rgba(28, 30, 38, 245);
    border: 1px solid {GLASS_BORDER};
    selection-background-color: {ACCENT};
    selection-color: #fff;
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    border: none;
    width: 16px;
}}

/* ---------- 滚动区域/条 ---------- */
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 9px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 45);
    border-radius: 4px;
    min-height: 36px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(255, 255, 255, 85);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 9px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(255, 255, 255, 45);
    border-radius: 4px;
    min-width: 36px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ---------- 卡片 ---------- */
QFrame#card {{
    background: {GLASS_CARD};
    border: 1px solid rgba(255, 255, 255, 32);
    border-radius: 12px;
}}
QLabel#cardImg {{
    background: rgba(255, 255, 255, 8);
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
    color: #7a8093;
}}
QLabel#cardTitle {{
    color: #eef0f6;
    background: transparent;
    font-size: 12px;
}}
QLabel#cardBadge {{
    color: {ACCENT_SOFT};
    background: transparent;
    font-size: 11px;
}}
QLabel#cardFav {{
    color: #ffd166;
    background: rgba(20, 22, 28, 180);
    border-radius: 8px;
    padding: 1px 8px;
    font-size: 11px;
}}

/* ---------- 分组/设置 ---------- */
QGroupBox {{
    background: transparent;
    border: 1px solid rgba(255, 255, 255, 28);
    border-radius: 10px;
    margin-top: 18px;
    padding-top: 10px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
    color: #a6acbe;
    background: transparent;
}}
QCheckBox {{
    spacing: 8px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 5px;
    border: 1px solid rgba(255, 255, 255, 70);
    background: {GLASS_PANEL};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: none;
}}

/* ---------- 菜单/状态栏/弹窗 ---------- */
QMenu {{
    background: rgba(28, 30, 38, 245);
    border: 1px solid {GLASS_BORDER};
    border-radius: 9px;
    padding: 4px;
}}
QMenu::item {{
    padding: 7px 26px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: rgba(255, 255, 255, 40);
}}
QStatusBar {{
    background: rgba(255, 255, 255, 8);
    color: #a0a6b8;
    border-top: 1px solid rgba(255, 255, 255, 18);
}}
QMessageBox {{
    background: #1c1e26;
}}
QMessageBox QLabel {{
    background: transparent;
    color: #e8eaf1;
}}
/* 原生对话框（无亚克力）保持纯色底，避免透出桌面 */
QDialog {{
    background: #1c1e26;
}}
QToolTip {{
    background: rgba(28, 30, 38, 245);
    color: #e8eaf1;
    border: 1px solid {GLASS_BORDER};
    padding: 4px 8px;
}}

/* ---------- 截图裁剪框 ---------- */
QLabel#cropHint {{
    color: #a0a6b8;
    background: transparent;
}}
"""


def apply_theme(app) -> None:
    app.setStyleSheet(QSS)
