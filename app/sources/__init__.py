"""在线开源壁纸源。"""
from __future__ import annotations

from typing import Optional

_PROXIES: Optional[dict] = None


def set_proxy(url: str) -> None:
    """设置全局代理，如 http://127.0.0.1:7890；空字符串表示直连。"""
    global _PROXIES
    url = (url or "").strip()
    _PROXIES = {"http": url, "https": url} if url else None


def get_proxies() -> Optional[dict]:
    return _PROXIES


def autodetect_proxy() -> str:
    """从 Windows 系统设置里读取代理地址，找不到返回空串。"""
    try:
        import winreg
        k = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        enabled, _ = winreg.QueryValueEx(k, "ProxyEnable")
        if not enabled:
            return ""
        server, _ = winreg.QueryValueEx(k, "ProxyServer")
        if server.startswith("http"):
            return server
        return f"http://{server}" if server else ""
    except Exception:
        return ""
