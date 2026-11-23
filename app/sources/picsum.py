"""Lorem Picsum 随机摄影壁纸（开源，无需 Key）。"""
from __future__ import annotations

import requests

from . import get_proxies

LIST_URL = "https://picsum.photos/v2/list"
UA = {"User-Agent": "MeWallpaper/0.1"}
TIMEOUT = 15


def random_list(page: int = 1, limit: int = 24) -> list[dict]:
    r = requests.get(LIST_URL, params={"page": page, "limit": limit},
                     headers=UA, timeout=TIMEOUT, proxies=get_proxies())
    r.raise_for_status()
    out = []
    for item in r.json():
        pid = item.get("id")
        w, h = item.get("width", 1920), item.get("height", 1080)
        out.append({
            "id": f"picsum-{pid}",
            "thumb": f"https://picsum.photos/id/{pid}/400/225",
            "path": f"https://picsum.photos/id/{pid}/{w}/{h}",
            "url": item.get("url", ""),
            "title": item.get("author", ""),
            "resolution": f"{w}x{h}",
            "tags": ["photography"],
        })
    return out


def random_one(width: int = 1920, height: int = 1080) -> str:
    """直接返回一张随机原图 URL。"""
    return f"https://picsum.photos/{width}/{height}"
