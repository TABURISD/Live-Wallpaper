# -*- coding: utf-8 -*-
"""闪屏排查专用事件日志：记录每个可能扰动壁纸窗口/mpv 的动作。"""
from __future__ import annotations

import threading
import time
from pathlib import Path

_lock = threading.Lock()
_path = Path(__file__).resolve().parent.parent / "flicker.log"


def log(msg: str) -> None:
    try:
        with _lock:
            with open(_path, "a", encoding="utf-8") as f:
                t = time.time()
                f.write(time.strftime("%H:%M:%S", time.localtime(t))
                        + f".{int(t * 1000) % 1000:03d} {msg}\n")
    except Exception:
        pass
