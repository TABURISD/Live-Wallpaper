"""mpv 播放后端（独立进程版）。

不再把 libmpv-2.dll 加载进本进程：官方构建内置 LuaJIT，其 Windows x64
SEH 异常（0xe24c4a02）会在嵌入场景随机炸掉宿主进程（python-mpv issue #305，
VEH 无解）。改为拉起官方 mpv.exe 作为子进程：

- 画面经 ``--wid=<宿主 HWND>`` 渲染进我们的纯 Win32 STATIC 子窗口；
- 播放控制走命名管道 JSON IPC（``--input-ipc-server``）；
- mpv 进程自己崩了也带不垮主程序：看门狗线程自动重拉并重载上次的文件。

mpv.exe 放在 app/players/，不入库，构建前由 packaging/fetch_mpv.py 获取。
找不到 exe 时 backend_available() 返回 False，调用方回退 Qt Multimedia。
"""
from __future__ import annotations

import ctypes
import itertools
import json
import os
import subprocess
import threading
import time
from pathlib import Path

from . import flicklog

EXE_DIR = Path(__file__).resolve().parent / "players"
MPV_EXE = EXE_DIR / "mpv.exe"

_state: bool | None = None
_error: str = ""

_pipe_counter = itertools.count(1)


def backend_available() -> bool:
    """mpv.exe 是否存在（只探测一次）。"""
    global _state, _error
    if _state is not None:
        return _state
    if MPV_EXE.exists() and MPV_EXE.stat().st_size > 20 * 1024 * 1024:
        _state = True
    else:
        _state = False
        _error = f"mpv.exe 不存在: {MPV_EXE}"
    return _state


def backend_error() -> str:
    backend_available()
    return _error


# ---------------------------------------------------------------------------
# 命名管道 JSON IPC（ctypes，无第三方依赖）
# ---------------------------------------------------------------------------
_kernel32 = ctypes.windll.kernel32

_kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                                  ctypes.c_uint32, ctypes.c_void_p,
                                  ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p]
_kernel32.CreateFileW.restype = ctypes.c_void_p
_kernel32.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                ctypes.c_void_p]
_kernel32.WriteFile.restype = ctypes.c_bool
_kernel32.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                               ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                               ctypes.c_void_p]
_kernel32.ReadFile.restype = ctypes.c_bool
_kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
_kernel32.CloseHandle.restype = ctypes.c_bool

# ---- OVERLAPPED 结构（管道异步读写，写永不无限期阻塞） ----
class _OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t),
                ("InternalHigh", ctypes.c_size_t),
                ("Offset", ctypes.c_ulong),
                ("OffsetHigh", ctypes.c_ulong),
                ("hEvent", ctypes.c_void_p)]


_kernel32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_bool,
                                   ctypes.c_bool, ctypes.c_void_p]
_kernel32.CreateEventW.restype = ctypes.c_void_p
_kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_kernel32.WaitForSingleObject.restype = ctypes.c_ulong
_kernel32.GetOverlappedResult.argtypes = [ctypes.c_void_p,
                                          ctypes.POINTER(_OVERLAPPED),
                                          ctypes.POINTER(ctypes.c_uint32),
                                          ctypes.c_bool]
_kernel32.GetOverlappedResult.restype = ctypes.c_bool
_kernel32.CancelIoEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_kernel32.CancelIoEx.restype = ctypes.c_bool
_kernel32.GetLastError.restype = ctypes.c_ulong

_INVALID = ctypes.c_void_p(-1).value

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
INFINITE = 0xFFFFFFFF


class _Ipc:
    """到 mpv 命名管道的极简 JSON IPC 客户端（overlapped I/O）。"""

    def __init__(self, pipe_name: str):
        self._name = pipe_name
        self._h = None
        self._lock = threading.Lock()
        self._rid = itertools.count(1)
        self._pending: dict[int, tuple[threading.Event, dict]] = {}
        self._reader: threading.Thread | None = None
        self._closed = False

    def connect(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while True:
            h = _kernel32.CreateFileW(self._name,
                                      GENERIC_READ | GENERIC_WRITE,
                                      0, None, OPEN_EXISTING,
                                      FILE_FLAG_OVERLAPPED, None)
            if h and h != _INVALID:
                self._h = h
                break
            if time.monotonic() > deadline:
                raise TimeoutError(f"连接 mpv IPC 管道超时: {self._name}")
            time.sleep(0.1)
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        buf = ctypes.create_string_buffer(65536)
        ov = _OVERLAPPED()
        ov.hEvent = _kernel32.CreateEventW(None, True, False, None)
        pending_bytes = b""
        while not self._closed and self._h:
            n = ctypes.c_uint32(0)
            ok = _kernel32.ReadFile(self._h, buf, 65536, ctypes.byref(n),
                                    ctypes.byref(ov))
            if not ok:
                if _kernel32.GetLastError() != ERROR_IO_PENDING:
                    break
                rc = _kernel32.WaitForSingleObject(ov.hEvent, INFINITE)
                if rc != WAIT_OBJECT_0 or self._closed:
                    break
                if not _kernel32.GetOverlappedResult(self._h, ctypes.byref(ov),
                                                     ctypes.byref(n), False):
                    break
            if n.value == 0:
                continue
            pending_bytes += buf.raw[:n.value]
            while b"\n" in pending_bytes:
                line, pending_bytes = pending_bytes.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8", "replace"))
                except Exception:
                    continue
                rid = msg.get("request_id")
                if rid in self._pending:
                    ev, box = self._pending.pop(rid)
                    box["msg"] = msg
                    ev.set()
        try:
            _kernel32.CloseHandle(ov.hEvent)
        except Exception:
            pass

    def command(self, *args, timeout: float = 3.0,
                fire_and_forget: bool = False) -> dict | None:
        """发送命令；非 forget 时等待并返回 {"error", "data", ...}。"""
        if not self._h or self._closed:
            return None
        obj: dict = {"command": list(args)}
        if not fire_and_forget:
            rid = next(self._rid)
            obj["request_id"] = rid
            ev = threading.Event()
            box: dict = {}
            self._pending[rid] = (ev, box)
        else:
            rid, ev, box = 0, None, {}
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        with self._lock:
            ov = _OVERLAPPED()
            ov.hEvent = _kernel32.CreateEventW(None, True, False, None)
            try:
                cbuf = ctypes.create_string_buffer(data)
                n = ctypes.c_uint32(0)
                ok = _kernel32.WriteFile(self._h, cbuf, len(data),
                                         ctypes.byref(n), ctypes.byref(ov))
                if not ok:
                    if _kernel32.GetLastError() != ERROR_IO_PENDING:
                        raise OSError("WriteFile failed")
                    rc = _kernel32.WaitForSingleObject(
                        ov.hEvent, int(timeout * 1000))
                    if rc == WAIT_TIMEOUT:          # mpv 不在读：取消并放弃
                        _kernel32.CancelIoEx(self._h, ctypes.byref(ov))
                        raise TimeoutError("pipe write timeout")
                    if not _kernel32.GetOverlappedResult(
                            self._h, ctypes.byref(ov), ctypes.byref(n), False):
                        raise OSError("WriteFile overlapped failed")
            except Exception:
                if not fire_and_forget:
                    self._pending.pop(rid, None)
                return None
            finally:
                try:
                    _kernel32.CloseHandle(ov.hEvent)
                except Exception:
                    pass
        if fire_and_forget:
            return None
        if not ev.wait(timeout):
            self._pending.pop(rid, None)
            return None
        return box.get("msg")

    def get(self, prop: str, timeout: float = 1.5):
        msg = self.command("get_property", prop, timeout=timeout)
        if not msg or msg.get("error") not in (None, "success"):
            return None
        return msg.get("data")

    def set(self, prop: str, value, timeout: float = 1.5) -> bool:
        msg = self.command("set_property", prop, value, timeout=timeout)
        return bool(msg) and msg.get("error") in (None, "success")

    def close(self) -> None:
        self._closed = True
        if self._h:
            try:
                _kernel32.CancelIoEx(self._h, None)   # 唤醒阻塞的读循环
            except Exception:
                pass
            try:
                _kernel32.CloseHandle(self._h)
            except Exception:
                pass
            self._h = None
        for ev, _box in self._pending.values():
            ev.set()
        self._pending.clear()


# ---------------------------------------------------------------------------
# 独立进程播放器
# ---------------------------------------------------------------------------
class MpvPlayer:
    """拉起 mpv.exe 子进程，把画面嵌入 wid 指定的 Win32 窗口。"""

    def __init__(self, wid: int, hwdec: bool = True, volume: int = 0,
                 loop: bool = True, extra_args: tuple | list = ()):
        self.loop = loop
        self._wid = int(wid)
        self._hwdec = hwdec
        self._volume = max(0, min(100, int(volume)))
        self._extra = list(extra_args)
        self._proc: subprocess.Popen | None = None
        self._ipc: _Ipc | None = None
        self._closing = False
        self._last_path: str | None = None
        self._gen = 0          # 代际：防止旧看门狗误重拉
        self._watch_thread: threading.Thread | None = None
        self._spawn()

    # ---- 进程生命周期 ----
    def _spawn(self) -> None:
        pipe = rf"\\.\pipe\MeWallpaper-mpv-{os.getpid()}-{next(_pipe_counter)}"
        args = [
            str(MPV_EXE),
            f"--wid={self._wid}",
            "--idle=yes",            # 无文件时保持存活，等 loadfile
            "--keep-open=yes",
            "--really-quiet",
            "--osc=no",              # 壁纸不要屏上控制台
            "--ytdl=no",
            f"--input-ipc-server={pipe}",
            f"--loop-file={'inf' if self.loop else 'no'}",
            f"--hwdec={'auto-safe' if self._hwdec else 'no'}",
            f"--volume={self._volume}",
            # 嵌入桌面层的交换链调优（实测结论）：
            # - flip 模型必须保持（bgra8/bitblt 模型在 WorkerW 层根本不显示；
            #   WGL/DX9 路径同样出不来），但任何 Z-order 扰动都会把 flip
            #   交换链踢出独立翻转平面 → 定时器里严禁无脑 SetWindowPos
            # - bgra8：本机显示器被识别为 HDR，auto 会选 10 位交换链，
            #   壁纸场景固定 8 位即可
            # - target-colorspace-hint=no：不向 DWM 申报 HDR 色彩空间，
            #   避免合成器做 HDR 色调映射
            "--d3d11-flip=yes",
            "--d3d11-output-format=bgra8",
            "--target-colorspace-hint=no",
        ] + self._extra
        # 调试/试验：允许用环境变量追加 mpv 参数（如切换渲染路径）
        extra_env = os.environ.get("MEWALLPAPER_MPV_ARGS", "").strip()
        if extra_env:
            args += extra_env.split()
        self._proc = subprocess.Popen(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        flicklog.log(f"mpv spawn pid={self._proc.pid} wid={self._wid}")
        self._ipc = _Ipc(pipe)
        self._ipc.connect(timeout=10.0)
        gen = self._gen
        self._watch_thread = threading.Thread(
            target=self._watch, args=(gen,), daemon=True)
        self._watch_thread.start()

    def _watch(self, gen: int) -> None:
        """看门狗：mpv 进程意外退出（如 LuaJIT SEH）时自动重拉。"""
        proc = self._proc
        if proc is None:
            return
        code = proc.wait()
        flicklog.log(f"mpv exited code={code} closing={self._closing}")
        if self._closing or gen != self._gen or self._last_path is None:
            return
        time.sleep(0.8)
        if self._closing or gen != self._gen:
            return
        try:
            flicklog.log("watchdog respawn mpv")
            self._respawn_locked()
            if self._last_path:
                self._cmd("loadfile", self._last_path, "replace")
        except Exception:
            pass

    def _respawn_locked(self) -> None:
        """（看门狗内）清理旧进程残留并重新拉起。"""
        self._gen += 1
        try:
            if self._ipc:
                self._ipc.close()
        except Exception:
            pass
        self._ipc = None
        try:
            if self._proc and self._proc.poll() is None:
                self._proc.kill()
        except Exception:
            pass
        self._spawn()

    # ---- 播放控制 ----
    def _cmd(self, *args, timeout: float = 3.0,
             fire_and_forget: bool = False) -> dict | None:
        ipc = self._ipc
        if ipc is None:
            return None
        try:
            return ipc.command(*args, timeout=timeout,
                               fire_and_forget=fire_and_forget)
        except Exception:
            return None

    def play(self, path: str) -> None:
        self._last_path = str(path)
        self._cmd("loadfile", str(path), "replace")

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(100, int(volume)))
        self._ipc and self._ipc.set("volume", self._volume)

    def set_loop(self, loop: bool) -> None:
        """运行时切换循环播放。"""
        self.loop = loop
        self._ipc and self._ipc.set("loop-file", "inf" if loop else "no")

    def set_fill_mode(self, style: str) -> None:
        """按静态壁纸同款「填充方式」语义调整视频画面：
        fill/stretch/span = 裁边铺满；fit/tile = 适应留边；
        center = 原始尺寸居中。"""
        ipc = self._ipc
        if ipc is None:
            return
        if style in ("fill", "stretch", "span"):
            ipc.set("panscan", 1.0)
            ipc.set("video-unscaled", False)
        elif style == "center":
            ipc.set("panscan", 0.0)
            ipc.set("video-unscaled", True)
        else:                       # fit / tile 等一律按「适应」
            ipc.set("panscan", 0.0)
            ipc.set("video-unscaled", False)

    def pause(self) -> None:
        self._ipc and self._ipc.set("pause", True)

    def resume(self) -> None:
        self._ipc and self._ipc.set("pause", False)

    def paused(self) -> bool:
        return bool(self._ipc and self._ipc.get("pause", timeout=0.6))

    def seek(self, sec: float, exact: bool = True) -> None:
        self._cmd("seek", float(sec), "absolute", "exact" if exact else "keyframe")

    def screenshot(self, out_path: str, timeout: float = 4.0) -> bool:
        """把当前帧写入 out_path（原视频分辨率，无 OSD/字幕叠加）。"""
        msg = self._cmd("screenshot-to-file", str(out_path), "video",
                        timeout=timeout)
        if msg is None or msg.get("error") not in (None, "success"):
            return False
        # 写盘是异步的，轮询确认文件出现
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                return True
            time.sleep(0.05)
        return False

    # ---- 状态查询 ----
    def video_size(self) -> tuple[int, int]:
        """已加载视频的分辨率（未就绪时返回 0,0）。"""
        try:
            params = self._ipc and self._ipc.get("video-params", timeout=0.8)
            if isinstance(params, dict):
                return int(params.get("w", 0)), int(params.get("h", 0))
        except Exception:
            pass
        return 0, 0

    def position(self) -> float:
        """当前播放位置（秒），未就绪返回 0。"""
        try:
            v = self._ipc and self._ipc.get("time-pos", timeout=0.8)
            return float(v) if v is not None else 0.0
        except Exception:
            return 0.0

    def duration(self) -> float:
        """视频总时长（秒），未就绪返回 0。"""
        try:
            v = self._ipc and self._ipc.get("duration", timeout=0.8)
            return float(v) if v is not None else 0.0
        except Exception:
            return 0.0

    def terminate(self) -> None:
        self._closing = True
        self._gen += 1
        ipc = self._ipc
        self._ipc = None
        if ipc:
            try:
                ipc.command("quit", timeout=1.0, fire_and_forget=True)
            except Exception:
                pass
            try:
                ipc.close()
            except Exception:
                pass
        proc = self._proc
        self._proc = None
        if proc:
            try:
                proc.wait(timeout=3.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._last_path = None
