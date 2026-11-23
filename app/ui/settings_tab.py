"""设置页：填充方式、轮播、视频壁纸、开机启动。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..config import Config


class SettingsTab(QWidget):
    changed = Signal()

    STYLES = [("fill", "填充（推荐）"), ("fit", "适应"), ("stretch", "拉伸"),
              ("span", "跨屏"), ("center", "居中"), ("tile", "平铺")]

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 填充方式
        g_style = QGroupBox("壁纸填充方式")
        f = QFormLayout(g_style)
        self.style = QComboBox()
        for key, label in self.STYLES:
            self.style.addItem(label, key)
        idx = [k for k, _ in self.STYLES].index(config.style)
        self.style.setCurrentIndex(max(0, idx))
        f.addRow("方式", self.style)
        lay.addWidget(g_style)

        # 轮播
        g_slide = QGroupBox("定时轮播")
        f2 = QFormLayout(g_slide)
        self.slideshow = QCheckBox("启用定时切换")
        self.slideshow.setChecked(config.get("slideshow_enabled", False))
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 24 * 60)
        self.minutes.setValue(int(config.get("slideshow_minutes", 30)))
        self.minutes.setSuffix(" 分钟")
        self.slide_source = QComboBox()
        self.slide_source.addItem("整个库", "library")
        self.slide_source.addItem("仅收藏", "favorites")
        self.slide_source.addItem("指定文件夹", "folder")
        ssrc = config.get("slideshow_source", "library")
        self.slide_source.setCurrentIndex(
            max(0, ["library", "favorites", "folder"].index(ssrc)))
        self.folder_btn = QPushButton("选择文件夹…")
        self.folder_label = QLabel(config.get("slideshow_folder", "") or "未选择")
        self.folder_label.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.folder_btn)
        row.addWidget(self.folder_label, stretch=1)
        f2.addRow(self.slideshow)
        f2.addRow("间隔", self.minutes)
        f2.addRow("来源", self.slide_source)
        f2.addRow(row)
        lay.addWidget(g_slide)

        # 在线源
        g_online = QGroupBox("在线源（Wallhaven）")
        f3 = QFormLayout(g_online)
        self.proxy = QLineEdit(config.get("proxy", ""))
        self.proxy.setPlaceholderText("留空自动用系统代理；direct 强制直连")
        f3.addRow("代理", self.proxy)
        self.api_key = QLineEdit(config.get("wallhaven_api_key", ""))
        self.api_key.setPlaceholderText("可选，留空则 45 次/分钟")
        f3.addRow("API Key", self.api_key)
        self.cats = QComboBox()
        self.cats.addItem("综合 + 动漫", "110")
        self.cats.addItem("仅综合", "100")
        self.cats.addItem("仅动漫", "010")
        self.cats.addItem("全部（含人物）", "111")
        cur = config.get("wallhaven_categories", "110")
        self.cats.setCurrentIndex(max(0, ["110", "100", "010", "111"].index(cur)))
        f3.addRow("分类", self.cats)
        lay.addWidget(g_online)

        # 视频壁纸
        g_video = QGroupBox("视频动态壁纸（实验性）")
        f4 = QFormLayout(g_video)
        self.volume = QSpinBox()
        self.volume.setRange(0, 100)
        self.volume.setValue(int(config.get("video_volume", 0)))
        self.volume.setSuffix(" %")
        self.hw = QCheckBox("尝试硬件解码")
        self.hw.setChecked(config.get("video_hw_decode", True))
        self.pause_fs = QCheckBox("其他程序全屏时暂停")
        self.pause_fs.setChecked(config.get("video_paused_on_fullscreen", True))
        self.stretch = QCheckBox("画面拉伸铺满（否则保持比例）")
        self.stretch.setChecked(config.get("video_stretch", False))
        f4.addRow("音量", self.volume)
        f4.addRow(self.hw)
        f4.addRow(self.pause_fs)
        f4.addRow(self.stretch)
        lay.addWidget(g_video)

        # 行为
        g_beh = QGroupBox("行为")
        f5 = QFormLayout(g_beh)
        self.autostart = QCheckBox("开机自动启动")
        self.autostart.setChecked(config.get("auto_start", False))
        hint = QLabel("快捷键：Ctrl+Alt+N 随机换一张壁纸")
        hint.setStyleSheet("color:#888;")
        f5.addRow(self.autostart)
        f5.addRow(hint)
        lay.addWidget(g_beh)

        lay.addStretch(1)

        # 事件
        self.style.currentIndexChanged.connect(self._save)
        self.slideshow.toggled.connect(self._save)
        self.minutes.valueChanged.connect(self._save)
        self.slide_source.currentIndexChanged.connect(self._save)
        self.proxy.editingFinished.connect(self._save)
        self.api_key.editingFinished.connect(self._save)
        self.cats.currentIndexChanged.connect(self._save)
        self.volume.valueChanged.connect(self._save)
        self.hw.toggled.connect(self._save)
        self.pause_fs.toggled.connect(self._save)
        self.stretch.toggled.connect(self._save)
        self.autostart.toggled.connect(self._save_autostart)
        self.folder_btn.clicked.connect(self._pick_folder)

    def _save(self, *_args):
        c = self.config
        c.set("wallpaper_style", self.style.currentData())
        c.set("slideshow_enabled", self.slideshow.isChecked())
        c.set("slideshow_minutes", self.minutes.value())
        c.set("slideshow_source", self.slide_source.currentData())
        raw_proxy = self.proxy.text().strip()
        c.set("proxy", raw_proxy)
        from ..sources import autodetect_proxy, set_proxy
        if not raw_proxy:
            set_proxy(autodetect_proxy())
        elif raw_proxy.lower() == "direct":
            set_proxy("")
        else:
            set_proxy(raw_proxy)
        c.set("wallhaven_api_key", self.api_key.text().strip())
        c.set("wallhaven_categories", self.cats.currentData())
        c.set("video_volume", self.volume.value())
        c.set("video_hw_decode", self.hw.isChecked())
        c.set("video_paused_on_fullscreen", self.pause_fs.isChecked())
        c.set("video_stretch", self.stretch.isChecked())
        self.changed.emit({"wallpaper_style", "video_stretch", "video_hw_decode",
                           "video_volume", "video_paused_on_fullscreen"})

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择轮播文件夹")
        if folder:
            self.config.set("slideshow_folder", folder)
            self.folder_label.setText(folder)
            self.changed.emit(set())

    def _save_autostart(self, checked: bool):
        self.config.set("auto_start", checked)
        from ..webapi import apply_autostart
        apply_autostart(checked)
        self.changed.emit(set())
