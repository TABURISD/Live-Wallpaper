"""API 向量测试：遍历 Web UI 用到的全部端点，逐项 PASS/FAIL。

复现用户反馈的三类问题：
1. "随便设置都出现了文件不存在" —— 用与前端完全相同的方式（取路径→POST /api/set）测；
2. 来回切换窗口 bug —— 校验核心窗口改名 + 预览/停止状态机；
3. 在线壁纸不可用 —— 三个在线源各搜索/缩略图/下载/设置走一遍。

注意：会真实改动系统壁纸，结束后自动恢复视频壁纸。
用法：先启动软件，再 python -u scripts/api_vector_test.py
"""
from __future__ import annotations

import ctypes
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:15216"
VIDEO = ROOT / "wallpapers" / "405bed4e8afb4596be7dc18860928e0f.mp4"
CONFIG_FILE = ROOT / "data" / "config.json"
TEST_DIR = ROOT / "scripts" / "_vectest"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def cfg() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def wait_state(pred, timeout=15.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = requests.get(f"{BASE}/api/state", timeout=3).json()
            if pred(s):
                return s
        except Exception:
            pass
        time.sleep(0.4)
    return None


def wait_cfg(pred, timeout=10.0) -> dict | None:
    """轮询 data/config.json 直到满足条件（bridge 调度 + SPI 线程都有延迟）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            c = cfg()
            if pred(c):
                return c
        except Exception:
            pass
        time.sleep(0.4)
    return None


def find_window(title: str) -> int:
    return ctypes.windll.user32.FindWindowW(None, title)


def main() -> int:
    # 0. 服务存活
    try:
        r = requests.get(f"{BASE}/api/state", timeout=5)
        check("0. API 存活 /api/state", r.status_code == 200, f"backend={r.json().get('backend')}")
    except Exception as ex:
        check("0. API 存活 /api/state", False, str(ex))
        return _summary()

    # 1. 本地库
    lib_all = requests.get(f"{BASE}/api/library?type=all", timeout=10).json()
    lib_img = requests.get(f"{BASE}/api/library?type=image", timeout=10).json()
    lib_vid = requests.get(f"{BASE}/api/library?type=video", timeout=10).json()
    check("1a. /api/library?type=all", isinstance(lib_all, list) and len(lib_all) >= 1, f"{len(lib_all)} 条")
    check("1b. type=image / type=video 过滤",
          all(e["type"] == "image" for e in lib_img) and all(e["type"] == "video" for e in lib_vid),
          f"image={len(lib_img)} video={len(lib_vid)}")

    ventry = next((e for e in lib_all if e["path"].lower().endswith(".mp4")), None)
    check("1c. 库中包含视频壁纸", ventry is not None, ventry["title"] if ventry else "")

    # 2. 缩略图与原图
    from urllib.parse import quote
    qp = quote(str(VIDEO), safe="")
    r = requests.get(f"{BASE}/api/thumb?path={qp}", timeout=15)
    check("2a. /api/thumb 视频封面", r.status_code == 200 and len(r.content) > 1000,
          f"{r.status_code}, {len(r.content)}B")
    r = requests.get(f"{BASE}/api/raw?path={qp}", timeout=20, stream=True)
    raw_ok = r.status_code == 200 and int(r.headers.get("Content-Length") or 0) > 1000000
    check("2b. /api/raw 原图/原片", raw_ok, f"{r.status_code}, {r.headers.get('Content-Length')}B")
    r.close()

    # 3. 设置壁纸 —— 错误路径（复现"文件不存在"）
    r = requests.post(f"{BASE}/api/set", json={"path": str(ROOT / "not_exist_不存在.png")}, timeout=10)
    err_msg = ""
    try:
        err_msg = r.json().get("error", "")
    except Exception:
        pass
    check("3a. /api/set 不存在路径返回 400", r.status_code == 400 and "不存在" in err_msg,
          f"{r.status_code} error={err_msg}")

    # 3b. 设置壁纸 —— 静态图（与前端相同流程：取路径 → POST）
    TEST_DIR.mkdir(exist_ok=True)
    img = TEST_DIR / "vector_test.png"
    from PIL import Image
    Image.new("RGB", (1920, 1080), (79, 110, 247)).save(img)
    r = requests.post(f"{BASE}/api/set", json={"path": str(img)}, timeout=10)
    c = wait_cfg(lambda c: c.get("current_wallpaper_type") == "image"
                 and Path(c.get("current_wallpaper", "")).resolve() == img.resolve()) or {}
    sys_wp = ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as k:
            sys_wp = winreg.QueryValueEx(k, "Wallpaper")[0]
    except Exception:
        pass
    check("3b. /api/set 静态图生效",
          r.json().get("ok") is True and c.get("current_wallpaper_type") == "image"
          and Path(c.get("current_wallpaper", "")).resolve() == img.resolve()
          and Path(sys_wp).resolve() == img.resolve(),
          f"config={c.get('current_wallpaper_type')}, 系统壁纸={'命中' if sys_wp else '未查到'}")

    # 3c. 设置壁纸 —— 动态视频（用户主投诉场景）
    r = requests.post(f"{BASE}/api/set", json={"path": str(VIDEO)}, timeout=10)
    s = wait_state(lambda s: s["video_attached"] and s["current"]["type"] == "video")
    c = cfg()
    check("3c. /api/set 动态视频挂载",
          r.json().get("ok") is True and s is not None and c.get("current_wallpaper_type") == "video",
          f"attached={s and s['video_attached']}, backend={s and s['backend']}")

    # 4. 预览状态机：预览 → 出现浮动窗 → stop_video 关掉（hide 后句柄仍在，判可见性）
    r = requests.post(f"{BASE}/api/preview_video", json={"path": str(VIDEO)}, timeout=10)
    hwnd, vis_before = 0, 0
    for _ in range(25):
        hwnd = find_window(f"预览 - {VIDEO.name}")
        if hwnd and ctypes.windll.user32.IsWindowVisible(hwnd):
            vis_before = 1
            break
        time.sleep(0.4)
    r2 = requests.post(f"{BASE}/api/stop_video", timeout=10)
    hwnd2, vis_after = hwnd, 1
    for _ in range(25):
        hwnd2 = find_window(f"预览 - {VIDEO.name}")
        vis_after = ctypes.windll.user32.IsWindowVisible(hwnd2) if hwnd2 else 0
        if vis_after == 0:
            break
        time.sleep(0.4)
    s = requests.get(f"{BASE}/api/state", timeout=5).json()
    check("4. 预览开窗 + stop_video 关窗",
          r.json().get("ok") and hwnd != 0 and vis_before == 1 and vis_after == 0 and not s["video_attached"],
          f"预览窗 hwnd={hwnd} 可见{vis_before}→{vis_after}")

    # 5. 收藏往返
    r1 = requests.post(f"{BASE}/api/favorite", json={"path": str(VIDEO)}, timeout=10).json()
    fav1 = r1.get("favorite")
    r2 = requests.post(f"{BASE}/api/favorite", json={"path": str(VIDEO)}, timeout=10).json()
    lib_now = requests.get(f"{BASE}/api/library?type=all", timeout=10).json()
    entry = next(e for e in lib_now if e["path"] == str(VIDEO))
    check("5. /api/favorite 收藏往返", fav1 is True and r2.get("favorite") is False and entry["favorite"] is False)

    # 6. 重命名往返
    orig_title = entry["title"]
    requests.post(f"{BASE}/api/rename", json={"path": str(VIDEO), "title": "向量测试临时名"}, timeout=10)
    e1 = next(e for e in requests.get(f"{BASE}/api/library?type=all", timeout=10).json()
              if e["path"] == str(VIDEO))
    requests.post(f"{BASE}/api/rename", json={"path": str(VIDEO), "title": orig_title}, timeout=10)
    e2 = next(e for e in requests.get(f"{BASE}/api/library?type=all", timeout=10).json()
              if e["path"] == str(VIDEO))
    check("6. /api/rename 重命名往返",
          e1["title"] == "向量测试临时名" and e2["title"] == orig_title, f"{orig_title}")

    # 7. 在线源：搜索 × 3（每次搜索会清空在线缓存，因此后续下载/缩略图
    #    必须用最后一次搜索的结果，与前端行为一致）
    last = None
    for src in ("Wallhaven", "必应每日", "Picsum"):
        try:
            r = requests.get(f"{BASE}/api/online/search",
                             params={"source": src, "query": "landscape" if src == "Wallhaven" else "",
                                     "page": 1}, timeout=40)
            items = r.json()
            ok = r.status_code == 200 and isinstance(items, list) and len(items) > 0
            check(f"7a. 在线搜索 {src}", ok, f"{len(items) if isinstance(items, list) else r.text[:60]} 条")
            if ok:
                last = (src, items[0])
        except Exception as ex:
            check(f"7a. 在线搜索 {src}", False, str(ex)[:80])

    # 8. 在线缩略图
    if last:
        src, it = last
        r = requests.get(f"{BASE}/api/online/thumb", params={"key": it["id"]}, timeout=40)
        check("8. 在线缩略图代理", r.status_code == 200 and len(r.content) > 500,
              f"{r.status_code} {len(r.content)}B ({src})")

    # 9. 在线下载 + 直接设置 + 轮播 + 删除（含文件）完整往返
    src, it = last
    r = requests.post(f"{BASE}/api/online/download",
                      json={"id": it["id"], "source": src, "set": True}, timeout=90)
    ok = False
    detail = r.text[:80]
    dest = None
    if r.status_code == 200 and r.json().get("ok"):
        dest = Path(r.json()["path"])
        c = wait_cfg(lambda c: c.get("current_wallpaper_type") == "image"
                     and Path(c.get("current_wallpaper", "")).resolve() == dest.resolve()) or {}
        ok = dest.exists() and dest.stat().st_size > 10000 \
            and c.get("current_wallpaper_type") == "image" \
            and Path(c.get("current_wallpaper", "")).resolve() == dest.resolve()
        detail = f"{dest.name} {dest.stat().st_size if dest.exists() else 0}B set:{ok}"
    check("9a. 在线下载+设置为壁纸", ok, detail)

    # 9b. 轮播立即切换（库中已有下载的图片，池非空）
    r = requests.post(f"{BASE}/api/slideshow/now", timeout=10)
    c = wait_cfg(lambda c: c.get("current_wallpaper_type") == "image") or {}
    check("9b. /api/slideshow/now", r.json().get("ok") is True and c.get("current_wallpaper_type") == "image",
          f"type={c.get('current_wallpaper_type')}")

    # 9c. 删除（连文件一起）
    if dest is not None:
        rd = requests.post(f"{BASE}/api/delete", json={"path": str(dest), "delete_file": True}, timeout=10)
        lib_after = requests.get(f"{BASE}/api/library?type=all", timeout=10).json()
        gone = all(e["path"] != str(dest) for e in lib_after) and not dest.exists()
        check("9c. /api/delete 删除条目+文件", rd.json().get("ok") and gone, f"文件存在={dest.exists()}")

    # 10. 设置项读写往返
    gs = requests.get(f"{BASE}/api/settings", timeout=10).json()
    mod = {"wallpaper_style": "fit" if gs.get("wallpaper_style") != "fit" else "fill",
           "video_volume": 25, "slideshow_minutes": 45,
           "video_loop": not gs.get("video_loop", True),
           "download_dir": gs.get("download_dir") or r"E:\LiveWallpaper"}
    requests.post(f"{BASE}/api/settings", json=mod, timeout=10)
    gs2 = requests.get(f"{BASE}/api/settings", timeout=10).json()
    roundtrip = all(gs2.get(k) == v for k, v in mod.items())
    restore = {k: gs.get(k) for k in mod}
    requests.post(f"{BASE}/api/settings", json=restore, timeout=10)
    gs3 = requests.get(f"{BASE}/api/settings", timeout=10).json()
    restored = all(gs3.get(k) == gs.get(k) for k in mod)
    check("10. /api/settings 读写+还原", roundtrip and restored,
          f"改{mod['wallpaper_style']}/vol25/min45 → 还原{'OK' if restored else 'FAIL'}")

    # 11. 扫描 / crop 空路径（不弹窗）
    r = requests.post(f"{BASE}/api/scan", timeout=10)
    check("11a. /api/scan", r.json().get("ok") is True)
    r = requests.post(f"{BASE}/api/crop", json={"path": ""}, timeout=10)
    check("11b. /api/crop 空路径不弹窗", r.json().get("ok") is True)
    r = requests.post(f"{BASE}/api/video_frame", json={"path": str(ROOT / "no.mp4")}, timeout=10)
    check("11c. /api/video_frame 坏路径返回 400", r.status_code == 400, f"{r.status_code}")

    # 11d. 在线页切走再切回：DOM 重建、结果回填（复现用户反馈「切换失败」）
    nav_js = "(p)=>{document.querySelector('.nav-item[data-page='+p+']').click();return p}"
    try:
        ok_nav = True
        detail = ""
        for pg in ("online", "images", "online"):
            r = requests.post(f"{BASE}/api/dev/eval", json={"code": f"({nav_js})('{pg}')"}, timeout=15)
            if not r.json().get("ok"):
                ok_nav = False
                detail = r.text[:60]
                break
            time.sleep(2.5 if pg == "online" else 0.5)
        chk = requests.post(f"{BASE}/api/dev/eval", json={"code":
            "(()=>{const g=document.getElementById('olGrid');"
            "return JSON.stringify({grid:!!g,page:state.page,"
            "cards:g?g.querySelectorAll('.card').length:0})})()"}, timeout=15)
        d = json.loads(chk.json()["result"])
        ok_nav = ok_nav and d["grid"] and d["page"] == "online" and d["cards"] > 0
        check("11d. 在线页来回切换正常", ok_nav, f"{d} {detail}")
    except Exception as ex:
        check("11d. 在线页来回切换正常", False, str(ex)[:80])

    # 12. 窗口重名检查：核心窗口应叫 MeWallpaperCore 且隐藏；「我的壁纸」应是 WebView2
    core_hwnd = find_window("MeWallpaperCore")
    ui_hwnd, ui_vis = 0, 0
    for _ in range(10):
        ui_hwnd = find_window("MeWallpaper")
        if ui_hwnd:
            ui_vis = ctypes.windll.user32.IsWindowVisible(ui_hwnd)
            break
        time.sleep(0.5)
    visible = ctypes.windll.user32.IsWindowVisible(core_hwnd) if core_hwnd else None
    check("12. 窗口重名修复",
          core_hwnd != 0 and visible == 0 and ui_hwnd != 0 and ui_hwnd != core_hwnd and ui_vis == 1,
          f"Core hwnd={core_hwnd} visible={visible}, 界面 hwnd={ui_hwnd} visible={ui_vis}")

    # 恢复：动态视频壁纸
    requests.post(f"{BASE}/api/set", json={"path": str(VIDEO)}, timeout=10)
    s = wait_state(lambda s: s["video_attached"])
    check("恢复. 视频壁纸已还原", s is not None and s["video_attached"])

    # 清理测试图片（保留在磁盘上供用户查看也行，这里删掉保持干净）
    try:
        img.unlink()
        TEST_DIR.rmdir()
    except Exception:
        pass

    return _summary()


def _summary() -> int:
    fails = [r for r in results if not r[1]]
    print(f"\n===== 向量测试：{len(results) - len(fails)}/{len(results)} 项通过 =====")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
