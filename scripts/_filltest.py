"""验证动态壁纸填充方式即时生效（读 mpv 属性）。"""
import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mpv_ipc import mpv_ipc

API = "http://127.0.0.1:15216"
MP4 = r"E:\LiveWallpaper\405bed4e8afb4596be7dc18860928e0f.mp4"

def post(ep, data):
    req = urllib.request.Request(API + ep, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status

pipes = [n for n in os.listdir(r"\\.\pipe") if n.startswith("MeWallpaper-mpv-")]
pipe = "\\\\.\\pipe\\" + pipes[0]

EXPECT = {"fill": (1.0, False), "stretch": (1.0, False), "span": (1.0, False),
          "center": (0.0, True), "fit": (0.0, False), "tile": (0.0, False)}

post("/api/set", {"path": MP4})
time.sleep(7)
fails = []
for style, (exp_pan, exp_uns) in EXPECT.items():
    post("/api/settings", {"wallpaper_style": style})
    time.sleep(3)
    r = mpv_ipc(pipe, [("pan", ["get_property", "panscan"]),
                       ("uns", ["get_property", "video-unscaled"])])
    pan, uns = r.get("pan"), r.get("uns")
    ok = abs((pan or 0) - exp_pan) < 0.01 and bool(uns) == exp_uns
    print(f"{style:8} panscan={pan} unscaled={uns} expect=({exp_pan},{exp_uns}) ok={ok}")
    if not ok:
        fails.append(style)

print("fails:", fails)
raise SystemExit(1 if fails else 0)
