"""Wallhaven 开源壁纸源。无需 API Key（45 次/分钟），可填 Key 提高额度。"""
from __future__ import annotations

import requests

from . import get_proxies

API = "https://wallhaven.cc/api/v1/search"
UA = {"User-Agent": "MeWallpaper/0.1 (personal use)"}
TIMEOUT = 15


def search(query: str = "", categories: str = "110", purity: str = "100",
           sorting: str = "favorites", ratios: str = "16x9",
           page: int = 1, api_key: str = "") -> list[dict]:
    """返回 [{id, thumb, url, path(原图), resolution, favorites, views, tags}]"""
    params = {
        "q": query,
        "categories": categories,
        "purity": purity,
        "sorting": sorting,
        "ratios": ratios,
        "page": page,
    }
    if api_key:
        params["apikey"] = api_key
    r = requests.get(API, params=params, headers=UA, timeout=TIMEOUT,
                     proxies=get_proxies())
    r.raise_for_status()
    out = []
    for item in r.json().get("data", []):
        out.append({
            "id": item.get("id"),
            "thumb": item.get("thumbs", {}).get("small") or item.get("thumbs", {}).get("large"),
            "url": item.get("url"),
            "path": item.get("path"),
            "resolution": item.get("resolution"),
            "file_size": item.get("file_size", 0),
            "favorites": item.get("favorites", 0),
            "views": item.get("views", 0),
            "tags": [t.get("name", "") for t in item.get("tags", [])][:6],
        })
    return out
