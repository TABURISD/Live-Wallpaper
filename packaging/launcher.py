# -*- coding: utf-8 -*-
"""MeWallpaper 打包入口（PyInstaller 冻结模式下 __name__ == "__main__"）。"""
import sys

if __name__ == "__main__":
    from app.__main__ import main
    sys.exit(main())
