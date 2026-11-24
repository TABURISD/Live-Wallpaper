"""用 ctypes 直连 mpv IPC 发命令。"""
import ctypes, json, time
from ctypes import wintypes


def mpv_ipc(pipe_path, commands):
    k = ctypes.windll.kernel32
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    k.CreateFileW.restype = wintypes.HANDLE
    GENERIC_READ, GENERIC_WRITE, OPEN_EXISTING = 0x80000000, 0x40000000, 3
    h = k.CreateFileW(pipe_path, GENERIC_READ | GENERIC_WRITE, 0, None,
                      OPEN_EXISTING, 0, None)
    if int(h) == -1:
        return None

    def write(obj):
        data = (json.dumps(obj) + "\n").encode()
        n = wintypes.DWORD(0)
        k.WriteFile(h, data, len(data), ctypes.byref(n), None)

    def readline(timeout_s=3.0):
        buf = ctypes.create_string_buffer(65536)
        n = wintypes.DWORD(0)
        t0 = time.time()
        data = b""
        while time.time() - t0 < timeout_s:
            ok = k.ReadFile(h, buf, 65535, ctypes.byref(n), None)
            if not ok or n.value == 0:
                time.sleep(0.05)
                continue
            data += buf.raw[:n.value]
            if b"\n" in data:
                line, _, _ = data.partition(b"\n")
                return line.decode(errors="ignore")
        return None

    out = {}
    for name, cmd in commands:
        write({"command": cmd})
        line = readline()
        try:
            out[name] = json.loads(line).get("data")
        except Exception:
            out[name] = line
    k.CloseHandle(h)
    return out
