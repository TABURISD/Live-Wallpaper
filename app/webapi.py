"""本地 Web API：给网页 UI 提供数据与操作入口。

只绑定 127.0.0.1。所有 Qt GUI 操作都通过 MainWindow.bridge_invoke()
调度回 GUI 线程执行，Flask 线程绝不直接碰 Qt 对象。
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from .config import Config, PROJECT_ROOT, DOWNLOAD_DIR
from .library import Library
from . import sources
from . import mpvbackend


def apply_autostart(checked: bool) -> bool:
    """开机自启：写/删注册表 Run 项。冻结的 exe 直接启动自身；开发模式用 pythonw -m app。

    开发模式经 wscript 隐藏启动：直接挂 cmd /c 会在登录时闪出黑色控制台窗口。
    """
    import sys
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
            winreg.KEY_SET_VALUE)
        with key:
            if checked:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}"'
                else:
                    from .config import PROJECT_ROOT, DATA_DIR
                    exe = sys.executable.replace("python.exe", "pythonw.exe")
                    inner = (f'cmd /c cd /d "{PROJECT_ROOT}" && '
                             f'"{exe}" -m app')
                    vbs = DATA_DIR / "autostart.vbs"
                    vbs.write_text(
                        'CreateObject("WScript.Shell").Run '
                        + '"{}"'.format(inner.replace('"', '""'))
                        + ', 0, False\n',
                        encoding="ascii")
                    cmd = f'wscript.exe "{vbs}"'
                winreg.SetValueEx(key, "MeWallpaper", 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, "MeWallpaper")
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False

WEB_DIR = PROJECT_ROOT / "web"
PORT = 15216

# 在线页搜索结果的临时缓存（key = 前端传来的 id）
_online_cache: dict[str, dict] = {}
_online_lock = threading.Lock()

# WebView2 窗口引用（__main__ 注入），用于 /api/dev/eval 开发调试端点
WEBVIEW_WINDOWS: list = []


def _thumb_url(e) -> str:
    return ""


def create_app(win) -> Flask:
    app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")
    config: Config = win.config
    library: Library = win.library

    # ---------- 通用 ----------
    @app.get("/")
    def index():
        return send_file(WEB_DIR / "index.html")

    @app.get("/api/state")
    def state():
        cur = config.get("current_wallpaper", "")
        ctype = config.get("current_wallpaper_type", "image")
        e = library.get(cur) if cur else None
        return jsonify({
            "current": {"path": cur, "type": ctype,
                        "title": e.name if e else (Path(cur).stem if cur else "")},
            "backend": win.video_window.backend if win.video_window else "",
            "mpv_dir": str(mpvbackend.MPV_EXE),
            "mpv_error": mpvbackend.backend_error(),
            "video_attached": bool(win.video_window and win.video_window.attached),
        })

    # ---------- 本地库 ----------
    @app.get("/api/library")
    def library_list():
        t = request.args.get("type", "all")
        entries = library.all()
        if t == "image":
            entries = [e for e in entries if e.type == "image"]
        elif t == "video":
            entries = [e for e in entries if e.type == "video"]
        out = [{
            "path": e.path, "title": e.name, "type": e.type,
            "favorite": e.favorite, "source": e.source,
            "thumb": f"/api/thumb?path={_q(e.path)}",
        } for e in entries]
        return jsonify(out)

    @app.get("/api/thumb")
    def thumb():
        p = request.args.get("path", "")
        tp = library.thumbnail(p)
        if tp and Path(tp).exists():
            return send_file(tp)
        return "", 404

    @app.get("/api/raw")
    def raw():
        p = Path(request.args.get("path", ""))
        if p.exists() and p.is_file():
            return send_file(str(p))
        return "", 404

    @app.post("/api/set")
    def set_wallpaper():
        p = (request.json or {}).get("path", "")
        if not p or not Path(p).exists():
            return jsonify({"ok": False, "error": "文件不存在"}), 400
        ext = Path(p).suffix.lower()
        if ext in {".mp4", ".mkv", ".webm", ".mov", ".avi", ".gif", ".m4v"}:
            win.bridge_invoke(lambda: win.set_video_wallpaper(p))
        else:
            win.bridge_invoke(lambda: win.set_image_wallpaper(p))
        return jsonify({"ok": True})

    @app.post("/api/stop_video")
    def stop_video():
        win.bridge_invoke(lambda: win.stop_video_wallpaper())
        return jsonify({"ok": True})

    @app.post("/api/preview_video")
    def preview_video():
        p = (request.json or {}).get("path", "")
        if p:
            win.bridge_invoke(lambda: win.preview_video(p))
        return jsonify({"ok": True})

    @app.post("/api/favorite")
    def favorite():
        p = (request.json or {}).get("path", "")
        on = library.toggle_favorite(p)
        return jsonify({"ok": True, "favorite": on})

    @app.post("/api/delete")
    def delete():
        d = request.json or {}
        library.remove(d.get("path", ""), bool(d.get("delete_file")))
        return jsonify({"ok": True})

    @app.post("/api/rename")
    def rename():
        d = request.json or {}
        library.set_title(d.get("path", ""), d.get("title", ""))
        return jsonify({"ok": True})

    @app.post("/api/import")
    def import_files():
        result: dict = {}

        def _dlg():
            from PySide6.QtWidgets import QFileDialog
            files, _ = QFileDialog.getOpenFileNames(
                win, "导入壁纸", "", "壁纸文件 (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.mkv *.webm *.mov *.avi *.gif)")
            added = 0
            for f in files:
                ext = Path(f).suffix.lower()
                etype = "video" if ext in {".mp4", ".mkv", ".webm", ".mov", ".avi", ".gif", ".m4v"} else "image"
                e = library.add(f, entry_type=etype, source="import")
                if etype == "video" and not e.cover:
                    e.cover = library.find_cover(e.path)
                    library.save()
                added += 1
            result["added"] = added

        win.bridge_invoke(_dlg)
        return jsonify({"ok": True})

    @app.post("/api/scan")
    def scan():
        # 纯文件扫描（不碰 Qt），在 Flask 线程同步执行并返回新增数量。
        # 覆盖：存储目录（在线下载位置）+ 壁纸目录 + 用户设定目录。
        folders: list[str] = []
        dl = config.get("download_dir")
        if dl:
            folders.append(str(dl))
        folders.extend(config.get("watch_folders", []) or [])
        default_wp = PROJECT_ROOT / "wallpapers"
        if default_wp.exists():
            folders.append(str(default_wp))
        total = 0
        seen = set()
        for f in folders:
            try:
                if f and f not in seen and Path(f).exists():
                    seen.add(f)
                    total += library.scan_folder(f)
            except Exception:
                pass
        return jsonify({"ok": True, "added": total})

    @app.post("/api/crop")
    def crop():
        p = (request.json or {}).get("path", "")
        if p:
            win.bridge_invoke(lambda: win._open_crop_dialog(p))
        return jsonify({"ok": True})

    @app.post("/api/video_frame")
    def video_frame():
        p = (request.json or {}).get("path", "")
        if p and Path(p).exists():
            win.bridge_invoke(lambda: win._open_frame_dialog(p))
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "文件不存在"}), 400

    @app.post("/api/open_folder")
    def open_folder():
        folder = (request.json or {}).get("path", "") or str(
            Path(config.get("download_dir") or DOWNLOAD_DIR))
        try:
            d = Path(folder)
            d.mkdir(parents=True, exist_ok=True)
            import subprocess
            subprocess.Popen(["explorer", str(d)])
            return jsonify({"ok": True})
        except Exception as ex:
            return jsonify({"ok": False, "error": str(ex)}), 500

    @app.post("/api/slideshow/now")
    def slide_now():
        win.bridge_invoke(win.next_wallpaper_async)
        return jsonify({"ok": True})

    # ---------- 在线源 ----------
    @app.get("/api/online/search")
    def online_search():
        src = request.args.get("source", "Wallhaven")
        query = request.args.get("query", "").strip()
        page = max(1, int(request.args.get("page", 1)))
        sorting = request.args.get("sorting", "favorites")
        try:
            if src == "Wallhaven":
                items = sources.wallhaven.search(
                    query=query,
                    categories=config.get("wallhaven_categories", "110"),
                    purity=config.get("wallhaven_purity", "100"),
                    sorting=sorting, ratios="16x9", page=page,
                    api_key=config.get("wallhaven_api_key", ""))
            elif src == "必应每日":
                items = sources.bing.daily(count=8)
            else:
                items = sources.picsum.random_list(page=page, limit=24)
        except Exception as ex:
            return jsonify({"ok": False, "error": str(ex)}), 502
        with _online_lock:
            _online_cache.clear()
            for it in items:
                _online_cache[str(it["id"])] = it
        return jsonify([{
            "id": str(it["id"]), "title": it.get("title") or str(it["id"]),
            "res": it.get("resolution", ""),
            "fav": it.get("favorites"),
            "thumb": f"/api/online/thumb?key={it['id']}",
        } for it in items])

    @app.get("/api/online/thumb")
    def online_thumb():
        key = request.args.get("key", "")
        with _online_lock:
            it = _online_cache.get(key)
        if not it:
            return "", 404
        try:
            import requests
            r = requests.get(it["thumb"], timeout=30,
                             headers={"User-Agent": "MeWallpaper/0.1"},
                             proxies=sources.get_proxies())
            r.raise_for_status()
            from io import BytesIO
            return send_file(BytesIO(r.content), mimetype=r.headers.get("Content-Type", "image/jpeg"))
        except Exception:
            return "", 502

    @app.post("/api/online/download")
    def online_download():
        d = request.json or {}
        key = str(d.get("id", ""))
        with _online_lock:
            it = _online_cache.get(key)
        if not it:
            return jsonify({"ok": False, "error": "记录不存在"}), 404
        try:
            import hashlib
            import requests
            dest_dir = Path(config.get("download_dir") or DOWNLOAD_DIR)
            dest_dir.mkdir(parents=True, exist_ok=True)
            h = hashlib.md5(it["path"].encode()).hexdigest()[:10]
            ext = ".jpg"
            for e2 in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
                if e2 in it["path"].lower().split("?")[0][-8:]:
                    ext = e2
                    break
            # 文件名：标题（安全化） + 短哈希，避免不同源重名覆盖
            safe = "".join(c for c in (it.get("title") or str(it["id"]))
                           if c not in '\\/:*?"<>|')[:60].strip() or str(it["id"])
            dest = dest_dir / f"{safe}-{h}{ext}"
            if not dest.exists():
                r = requests.get(it["path"], timeout=60,
                                 headers={"User-Agent": "MeWallpaper/0.1"},
                                 proxies=sources.get_proxies())
                r.raise_for_status()
                dest.write_bytes(r.content)
            src = {"Wallhaven": "wallhaven", "必应每日": "bing"}.get(
                d.get("source", ""), "picsum")
            library.add(str(dest), source=src, title=it.get("title", ""),
                        tags=it.get("tags", []))
            if d.get("set"):
                win.bridge_invoke(lambda: win.set_image_wallpaper(str(dest)))
            return jsonify({"ok": True, "path": str(dest)})
        except Exception as ex:
            return jsonify({"ok": False, "error": str(ex)}), 502

    # ---------- 设置 ----------
    @app.get("/api/settings")
    def get_settings():
        keys = ["wallpaper_style", "slideshow_enabled", "slideshow_minutes",
                "slideshow_source", "watch_folders", "proxy",
                "wallhaven_api_key", "wallhaven_categories", "wallhaven_purity",
                "video_volume", "video_paused_on_fullscreen", "video_stretch",
                "video_hw_decode", "video_loop", "download_dir",
                "auto_start"]
        return jsonify({k: config.get(k) for k in keys})

    @app.post("/api/settings")
    def save_settings():
        d = request.json or {}
        for k, v in d.items():
            config.set(k, v)
        if "auto_start" in d:
            win.bridge_invoke(lambda: apply_autostart(bool(d["auto_start"])))
        win.bridge_invoke(lambda ks=set(d.keys()): win._on_settings_changed(ks))
        return jsonify({"ok": True})

    # ---------- 开发调试：在 WebView2 里执行 JS（仅 127.0.0.1）----------
    # 默认关闭；设置环境变量 MEWALLPAPER_DEBUG=1 才开启（发布版不应开启）
    @app.post("/api/dev/eval")
    def dev_eval():
        if os.environ.get("MEWALLPAPER_DEBUG", "") != "1":
            return jsonify({"ok": False, "error": "disabled"}), 404
        code = (request.json or {}).get("code", "")
        if not WEBVIEW_WINDOWS:
            return jsonify({"ok": False, "error": "no webview window"}), 503
        try:
            result = WEBVIEW_WINDOWS[-1].evaluate_js(code)
            return jsonify({"ok": True, "result": result})
        except Exception as ex:
            return jsonify({"ok": False, "error": str(ex)}), 500

    return app


def _q(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


def start_server(win) -> tuple[Flask, int]:
    app = create_app(win)
    t = threading.Thread(target=lambda: app.run(
        host="127.0.0.1", port=PORT, threaded=True,
        use_reloader=False, debug=False),
        daemon=True)
    t.start()
    return app, PORT
