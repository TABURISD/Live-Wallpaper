"""切换回归：循环 + 快速连点。"""
import json, time, urllib.request

API = "http://127.0.0.1:15216"
MP4 = r"E:\LiveWallpaper\405bed4e8afb4596be7dc18860928e0f.mp4"
JPG = r"E:\LiveWallpaper\6kpko7-ca2c973d4e.jpg"

def post(ep, data):
    req = urllib.request.Request(API + ep, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status

def state():
    with urllib.request.urlopen(API + "/api/state", timeout=10) as r:
        return json.loads(r.read())

fails = []
def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + "  " + detail)
    if not ok:
        fails.append(name)

for expect, p in [("image", JPG), ("video", MP4), ("image", JPG), ("video", MP4)]:
    post("/api/set", {"path": p}); time.sleep(7)
    s = state()
    check(f"switch->{expect}", s["current"]["path"] == p and s["current"]["type"] == expect
          and (expect == "image" or s["video_attached"]),
          f"type={s['current']['type']} attached={s['video_attached']}")

post("/api/set", {"path": JPG}); time.sleep(1.5)
post("/api/set", {"path": JPG}); time.sleep(1.5)
post("/api/set", {"path": MP4})
post("/api/set", {"path": MP4})
time.sleep(7)
s = state()
check("rapid->video", s["current"]["type"] == "video" and s["video_attached"],
      f"err={s['mpv_error']!r}")
time.sleep(8)
s = state()
check("stable", s["video_attached"] and s["current"]["type"] == "video")

print()
print("ALL PASS" if not fails else f"fails: {fails}")
raise SystemExit(1 if fails else 0)
