"""必应每日壁纸（官方开放接口，无需 Key）。"""
from __future__ import annotations

import requests

from . import get_proxies

URL = "https://www.bing.com/HPImageArchive.aspx"
UA = {"User-Agent": "MeWallpaper/0.1"}
TIMEOUT = 15


def daily(count: int = 8) -> list[dict]:
    """返回最近 count 天的必应壁纸 [{thumb, path, title, copyright}]"""
    params = {"format": "js", "idx": 0, "n": min(count, 8), "mkt": "zh-CN"}
    r = requests.get(URL, params=params, headers=UA, timeout=TIMEOUT,
                     proxies=get_proxies())
    r.raise_for_status()
    out = []
    for item in r.json().get("images", []):
        base = "https://www.bing.com"
        out.append({
            "id": f"bing-{item.get('startdate')}",
            "thumb": base + item.get("url", ""),
            "path": base + item.get("url", "").replace("_1920x1080", "_UHD"),
            "url": item.get("copyrightlink") or "https://www.bing.com",
            "title": item.get("title", ""),
            "resolution": "UHD",
            "tags": [item.get("copyright", "")[:20]],
        })
    return out
