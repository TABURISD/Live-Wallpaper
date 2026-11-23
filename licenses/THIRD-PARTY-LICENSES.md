# 第三方组件许可证

本项目（MeWallpaper）以 [MIT](../LICENSE) 许可证发布。以下为本软件分发时捆绑或依赖的第三方组件及其许可证。各组件的完整许可证文本随其官方发行版提供（PyPI 源代码分发包内均包含完整文本）。

## 动态链接 / 动态加载的组件（与本项目许可证相互独立）

| 组件 | 版本 | 许可证 | 使用方式 |
|---|---|---|---|
| Qt for Python (PySide6 / PySide6-Essentials / PySide6-Addons) | 6.12.0 | LGPL-3.0-only **或** GPL-2.0-only **或** GPL-3.0-only（由使用者择一） | 本项目以 **LGPL-3.0** 条款动态链接使用，未修改 Qt 源码。LGPL-3.0 要求：允许最终用户用自己的 Qt 版本替换之（本软件通过标准动态链接加载未修改的官方 PySide6  wheel，满足该要求）。完整文本：<https://www.gnu.org/licenses/lgpl-3.0.txt>，源码：<https://download.qt.io/official_releases/QtForPython/> |
| mpv (mpv.exe，官方 Windows 完整构建) | 见 `app/players/` | GPL-2.0-or-later **或** LGPL-2.1-or-later（官方构建可按 LGPL-2.1+ 使用） | 以独立子进程方式调用（`--wid` 嵌入 + 命名管道 IPC），仅进程间协作，不属于衍生作品。mpv 源码：<https://github.com/mpv-player/mpv> |
| Microsoft Edge WebView2 Runtime | 系统组件 | Microsoft 软件许可条款 | 不在安装包内分发；使用系统已安装的 WebView2 运行时，其许可见 <https://www.microsoft.com/en-us/legal/terms-of-use> |

## Python 依赖（全部许可证与 MIT 兼容，保留版权声明即可）

| 组件 | 版本 | 许可证 |
|---|---|---|
| requests | 2.33.1 | Apache-2.0 |
| Pillow | 12.2.0 | MIT-CMU（PIL Software License） |
| Flask | 3.1.3 | BSD-3-Clause |
| Werkzeug | 3.1.9 | BSD-3-Clause |
| pywebview | 6.2.1 | BSD-3-Clause |
| bottle | 0.13.4 | MIT |
| urllib3 | 2.6.3 | MIT |
| certifi | 2026.4.22 | MPL-2.0 |
| charset-normalizer | 3.4.7 | MIT |
| idna | 3.13 | BSD-3-Clause |
| click | 8.5.0 | BSD-3-Clause |
| Jinja2 | 3.1.6 | BSD-3-Clause |
| MarkupSafe | 3.0.3 | BSD-3-Clause |
| blinker | 1.9.0 | MIT |
| itsdangerous | 2.2.0 | BSD-3-Clause |
| proxy-tools | 0.1.0 | MIT |

## 说明

- 本项目的源代码（`app/`、`web/`、`scripts/`、`packaging/`）为原创实现，以 MIT 发布，不包含任何第三方 GPL/LGPL 源码的修改副本。
- 在线壁纸内容来自 Wallhaven、必应每日壁纸、Picsum 等公开 API，图片版权归各自作者所有，仅用于个人桌面壁纸用途。
- 应用 Logo（`web/assets/logo.png` / `logo.ico`）为本项目原创设计，随项目以 MIT 许可一并发布。
