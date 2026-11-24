"""Wikimedia Commons 视频源（免 API Key，CC 授权视频）。

通过 MediaWiki API 搜索 filetype:video 的媒体文件，返回可直接下载的
原始文件地址（webm/ogv/mp4）。国内访问需要代理（软件会自动探测系统代理，
也可在设置里手动指定）。
"""
from __future__ import annotations

import html
import re

import requests

from . import get_proxies

API = "https://commons.wikimedia.org/w/api.php"
# Wikimedia 对 UA 有明确要求：需带可识别的应用名与联系方式，
# 否则按滥用流量 429 处理（代理共享出口 IP 更容易触发）
UA = {"User-Agent": "MeWallpaper/1.0 (https://github.com/TABURISD/Live-Wallpaper; personal use)"}
TIMEOUT = 20
VIDEO_MIME = {"video/webm", "video/ogg", "video/mp4", "video/quicktime"}


def _strip_markup(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def search(query: str = "", page: int = 1, limit: int = 24) -> list[dict]:
    """返回 [{id, thumb, url, path(原文件), resolution, title, tags}]"""
    q = f"{query} filetype:video" if query.strip() else "filetype:video"
    params = {
        "action": "query", "format": "json",
        "generator": "search",
        "gsrsearch": q,
        "gsrnamespace": 6,          # File 命名空间
        "gsrlimit": limit,
        "gsroffset": (max(1, page) - 1) * limit,
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": 640,
    }
    r = requests.get(API, params=params, headers=UA, timeout=TIMEOUT,
                     proxies=get_proxies())
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", {})
    out = []
    for page_id, p in pages.items():
        infos = p.get("imageinfo") or []
        if not infos:
            continue
        ii = infos[0]
        if ii.get("mime") not in VIDEO_MIME:
            continue
        em = ii.get("extmetadata") or {}
        title = _strip_markup((em.get("ImageDescription") or {}).get("value", ""))
        if not title:
            title = p.get("title", "").replace("File:", "").rsplit(".", 1)[0]
        width = ii.get("width") or 0
        height = ii.get("height") or 0
        out.append({
            "id": f"wikimedia-{page_id}",
            "thumb": ii.get("thumburl") or "",   # 视频的海报帧
            "url": ii.get("descriptionurl") or "",
            "path": ii.get("url") or "",          # 原文件直链
            "resolution": f"{width}x{height}" if width else "",
            "file_size": ii.get("size") or 0,
            "title": title[:120],
            "tags": [],
            "video": True,
        })
    return out
