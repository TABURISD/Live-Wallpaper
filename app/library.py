"""本地壁纸库：扫描文件夹、收藏、标签、缩略图缓存。纯 JSON 本地存储。"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .config import IMAGE_EXTS, VIDEO_EXTS, LIBRARY_FILE, THUMB_DIR, ensure_dirs

ThumbCallback = Callable[[str, str], None]  # (wallpaper_id, thumb_path)


def wallpaper_id(path: str) -> str:
    import hashlib
    return hashlib.md5(path.encode("utf-8")).hexdigest()


class WallpaperEntry:
    def __init__(self, d: dict):
        self.path: str = d.get("path", "")
        self.type: str = d.get("type", "image")  # image | video
        self.title: str = d.get("title", "")
        self.tags: list[str] = list(d.get("tags", []))
        self.favorite: bool = bool(d.get("favorite", False))
        self.source: str = ("sidecar" if d.get("source") == "juying"
                        else d.get("source", "local"))  # local | wallhaven | bing | picsum | sidecar
        self.added_at: float = d.get("added_at", time.time())
        self.cover: str = d.get("cover", "")  # 视频封面图路径

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "type": self.type,
            "title": self.title,
            "tags": self.tags,
            "favorite": self.favorite,
            "source": self.source,
            "added_at": self.added_at,
            "cover": self.cover,
        }

    @property
    def name(self) -> str:
        return self.title or Path(self.path).stem

    @property
    def exists(self) -> bool:
        return Path(self.path).exists()


class Library:
    """壁纸库。entry 以 path 为唯一键持久化。"""

    def __init__(self) -> None:
        ensure_dirs()
        self._entries: dict[str, WallpaperEntry] = {}
        self._lock = threading.Lock()
        self.load()

    # ---------- 持久化 ----------
    def load(self) -> None:
        if LIBRARY_FILE.exists():
            try:
                raw = json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
                for d in raw.get("entries", []):
                    e = WallpaperEntry(d)
                    self._entries[e.path] = e
            except Exception:
                pass

    def save(self) -> None:
        with self._lock:
            payload = {"entries": [e.to_dict() for e in self._entries.values()]}
            LIBRARY_FILE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    # ---------- 增删改 ----------
    @staticmethod
    def _detect_type(path: str) -> str:
        ext = Path(path).suffix.lower()
        return "video" if ext in VIDEO_EXTS else "image"

    def add(self, path: str, entry_type: str | None = None, source: str = "local",
            title: str = "", tags: Optional[list[str]] = None) -> WallpaperEntry:
        p = str(Path(path).resolve())
        if entry_type is None:
            entry_type = self._detect_type(p)
        e = self._entries.get(p)
        if e is None:
            e = WallpaperEntry({"path": p, "type": entry_type, "source": source})
            self._entries[p] = e
        elif e.type != self._detect_type(p):
            # 已有记录的类型与真实文件不符（历史脏数据）→ 按扩展名纠正
            e.type = self._detect_type(p)
        if title:
            e.title = title
        if tags:
            e.tags = list(dict.fromkeys(e.tags + tags))
        self.save()
        return e

    def remove(self, path: str, delete_file: bool = False) -> None:
        p = str(Path(path).resolve()) if Path(path).exists() else path
        self._entries.pop(p, None)
        if delete_file:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
        # 清理缩略图
        (THUMB_DIR / f"{wallpaper_id(p)}.jpg").unlink(missing_ok=True)
        self.save()

    def toggle_favorite(self, path: str) -> bool:
        e = self._entries.get(path)
        if not e:
            e = self.add(path)
        e.favorite = not e.favorite
        self.save()
        return e.favorite

    def set_title(self, path: str, title: str) -> None:
        e = self._entries.get(path)
        if e:
            e.title = title
            self.save()

    def set_tags(self, path: str, tags: list[str]) -> None:
        e = self._entries.get(path)
        if e:
            e.tags = tags
            self.save()

    # ---------- 查询 ----------
    def get(self, path: str) -> Optional[WallpaperEntry]:
        return self._entries.get(path)

    def all(self, include_missing: bool = False) -> list[WallpaperEntry]:
        items = list(self._entries.values())
        if not include_missing:
            items = [e for e in items if e.exists]
        return sorted(items, key=lambda e: e.added_at, reverse=True)

    def favorites(self) -> list[WallpaperEntry]:
        return [e for e in self.all() if e.favorite]

    def videos(self) -> list[WallpaperEntry]:
        return [e for e in self.all() if e.type == "video"]

    def images(self) -> list[WallpaperEntry]:
        return [e for e in self.all() if e.type == "image"]

    def in_folder(self, folder: str) -> list[WallpaperEntry]:
        f = Path(folder).resolve()
        return [e for e in self.all() if f in Path(e.path).resolve().parents]

    def scan_folder(self, folder: str, recursive: bool = True) -> int:
        """扫描文件夹把图片/视频加入库，返回新增数量。识别 .metadata 侧车文件的封面与标题。

        去重策略：路径相同跳过；文件名+大小与库中某条目相同也跳过
        （同一份文件常被复制到多个目录，避免库里出现两条记录）。
        """
        added = 0
        root = Path(folder)
        iterator = root.rglob("*") if recursive else root.glob("*")
        existing_sizes: dict[str, int] = {}
        for e in self._entries.values():
            try:
                existing_sizes.setdefault(Path(e.path).name,
                                          Path(e.path).stat().st_size)
            except Exception:
                continue
        for p in iterator:
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
                continue
            if p.parent.name == ".metadata":   # 封面/meta 不单独入库
                continue
            key = str(p.resolve())
            if key in self._entries:
                # 已入库但类型与扩展名不符（历史脏数据）→ 顺手纠正
                _e = self._entries[key]
                _t = "video" if ext in VIDEO_EXTS else "image"
                if _e.type != _t:
                    _e.type = _t
                continue
            try:
                if existing_sizes.get(p.name) == p.stat().st_size:
                    continue   # 同一份文件已在库中（另一个目录的副本）
            except Exception:
                pass
            entry_type = "video" if ext in VIDEO_EXTS else "image"
            e = WallpaperEntry({"path": key, "type": entry_type})
            if entry_type == "video":
                meta = self._sidecar_meta(key)
                if meta:
                    e.source = "sidecar"
                    e.title = meta.get("title") or ""
                e.cover = self.find_cover(key)
            self._entries[key] = e
            try:
                existing_sizes[p.name] = p.stat().st_size
            except Exception:
                pass
            added += 1
        self.save()
        return added

    # ---------- 缩略图 ----------
    def find_cover(self, path: str) -> str:
        """找视频封面：优先 .metadata/<id>.cover.jpg 侧车文件，其次同级同名图片。"""
        p = Path(path)
        candidates = [
            p.parent / ".metadata" / f"{p.stem}.cover.jpg",
            p.with_suffix(".cover.jpg"),
            p.with_suffix(".jpg"),
            p.with_suffix(".png"),
        ]
        for c in candidates:
            if c.exists():
                return str(c)
        return ""

    def _sidecar_meta(self, path: str) -> dict:
        """读取 .metadata/<id>.meta.json 侧车元数据（标题等）。"""
        p = Path(path)
        meta = p.parent / ".metadata" / f"{p.stem}.meta.json"
        if meta.exists():
            try:
                return json.loads(meta.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def thumbnail(self, path: str, size: int = 400) -> Optional[str]:
        """生成（或复用）缩略图。视频条目用封面图。"""
        e = self._entries.get(path)
        if e and e.type == "video":
            cover = e.cover or self.find_cover(path)
            return self._make_thumb(cover, size) if cover else None
        return self._make_thumb(path, size)

    def _make_thumb(self, image_path: str, size: int) -> Optional[str]:
        wid = wallpaper_id(image_path)
        thumb_path = THUMB_DIR / f"{wid}.jpg"
        if thumb_path.exists():
            return str(thumb_path)
        try:
            from PIL import Image
            img = Image.open(image_path)
            img = img.convert("RGB")
            img.thumbnail((size, size))
            img.save(thumb_path, "JPEG", quality=82)
            return str(thumb_path)
        except Exception:
            return None
