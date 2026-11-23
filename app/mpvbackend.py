"""mpv (libmpv) 播放后端。

libmpv-2.dll 官方构建放在 app/players/，启动时把该目录加入 DLL 搜索路径。
找不到 DLL 或加载失败时 backend_available() 返回 False，调用方回退 Qt Multimedia。
"""
from __future__ import annotations

import os
from pathlib import Path

DLL_DIR = Path(__file__).resolve().parent / "players"

_state: bool | None = None


def backend_available() -> bool:
    """libmpv 是否可用（只探测一次）。"""
    global _state
    if _state is not None:
        return _state
    try:
        os.add_dll_directory(str(DLL_DIR))
    except Exception:
        pass
    os.environ["PATH"] = str(DLL_DIR) + os.pathsep + os.environ.get("PATH", "")
    try:
        import mpv  # noqa: F401
        _state = True
    except Exception:
        _state = False
    return _state


class MpvPlayer:
    """把 mpv 嵌入一个已有的 Win32 窗口（wid）播放。"""

    def __init__(self, wid: int, hwdec: bool = True, volume: int = 0,
                 loop: bool = True):
        import mpv
        self.loop = loop
        # 不指定 vo/gpu-context，让 mpv 在 Windows 上自动选择 d3d11：
        # 壁纸窗口是 WorkerW 的子窗口，WGL(gpu-context=win) 的呈现到不了
        # 桌面合成路径（实测窗口透明、画面出不来），d3d11 交换链才能被
        # DWM 正常合成到桌面层。闪屏问题由 Qt 侧的背景擦除控制解决。
        self._m = mpv.MPV(
            wid=str(int(wid)),
            loop="inf" if loop else "no",
            **{"hwdec": "auto-safe" if hwdec else "no",
               "keep-open": "yes",
               "really-quiet": "",
               "ytdl": "no",
               "volume": str(max(0, min(100, volume)))})

    def play(self, path: str) -> None:
        self._m.play(str(path))

    def set_volume(self, volume: int) -> None:
        try:
            self._m.volume = max(0, min(100, volume))
        except Exception:
            pass

    def set_loop(self, loop: bool) -> None:
        """运行时切换循环播放。"""
        self.loop = loop
        try:
            self._m.loop = "inf" if loop else "no"
        except Exception:
            pass

    def pause(self) -> None:
        try:
            self._m.pause = True
        except Exception:
            pass

    def resume(self) -> None:
        try:
            self._m.pause = False
        except Exception:
            pass

    def video_size(self) -> tuple[int, int]:
        """已加载视频的分辨率（未就绪时返回 0,0）。"""
        try:
            params = self._m.video_params
            if params:
                return int(params.get("w", 0)), int(params.get("h", 0))
        except Exception:
            pass
        return 0, 0

    def terminate(self) -> None:
        try:
            self._m.terminate()
        except Exception:
            pass

    def position(self) -> float:
        """当前播放位置（秒），未就绪返回 0。"""
        try:
            return float(self._m.time_pos or 0)
        except Exception:
            return 0.0

    def duration(self) -> float:
        """视频总时长（秒），未就绪返回 0。"""
        try:
            return float(self._m.duration or 0)
        except Exception:
            return 0.0
