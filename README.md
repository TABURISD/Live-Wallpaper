# MeWallpaper · 我的壁纸

**本地化**个人壁纸软件。无账号、无线上数据库，所有数据只存在本机；在线浏览只调用开放的壁纸 API。

![logo](web/assets/logo.png)

## 功能

**本地库（动态 / 静态分开管理）**

- **静态壁纸**：双击直接设为壁纸；右键「区域截图设置壁纸」可在图上框选区域（自由 / 16:9 / 9:16 / 4:3 / 屏幕比例）裁剪后设置；支持收藏、重命名、搜索
- **动态壁纸**：视频列表带封面缩略图，双击设为桌面动态壁纸（mpv 内核，硬解、通吃编码、循环播放），右键可窗口预览（关闭预览自动恢复壁纸）、视频截帧（mpv 渲染，不卡死）、停止
- **一键导入**：把存储目录（默认 `E:\LiveWallpaper`，可改）和监视目录下的壁纸文件一次性导入库中
- 导入文件 / 扫描目录；右键打开所在文件夹、移除出库、删除文件（可选连同磁盘文件一起删）
- 删除保护：同文件名同大小的重复文件自动去重，不会把同一份壁纸导成两条

**在线发现（开放 API，免登录）**

- Wallhaven：关键词搜索、分类筛选、多种排序、翻页（可选填 API Key）
- 必应每日：最近 8 天必应每日壁纸（UHD 原图）
- Picsum：随机摄影图
- 一键下载到存储目录并自动入库 / 下载并直接设为壁纸

**壁纸引擎**

- 六种填充方式：填充 / 适应 / 拉伸 / 居中 / 平铺 / 跨屏，**修改后立即对当前壁纸生效**
- 定时轮播：自定义间隔与来源（全部库 / 仅收藏 / 指定文件夹）
- 快捷键 `Ctrl + Alt + N` 随机换一张
- 动态壁纸：mpv (libmpv) 内核嵌入桌面 WorkerW 层，支持音量（热更新）、循环开关、画面拉伸/保持比例、硬件解码开关、其他程序全屏时自动暂停
- 系统托盘：双击打开主界面、快捷切换、停止动态壁纸、退出（退出不驻留）
- 开机自启（注册表 Run 项，安装版/免安装版均可用）
- 单实例运行：重复启动只会唤起已有窗口

## 安装

下载 `MeWallpaper-Setup.exe` 运行即可（Inno Setup 打包，无需 Python）。安装后：

- 程序位于 `C:\Program Files\MeWallpaper`（或你选择的目录）
- 配置、壁纸库、缩略图存在 `%LOCALAPPDATA%\MeWallpaper\data`（Program Files 无写权限，首次运行自动迁移免安装版的数据）
- 开始菜单 / 桌面快捷方式；设置页可开关开机自启；控制面板可卸载

系统要求：Windows 10 1803+（需 WebView2 运行时，Win10 21H2+/Win11 已内置）。

## 免安装运行（开发/验证）

```bat
pip install -r requirements.txt
python -m app
```

- 数据默认写在项目内 `data/`（免安装版目录可写时）；装到只读位置则自动切到 `%LOCALAPPDATA%\MeWallpaper\data`
- `--classic` 使用纯 Qt 界面（不启 WebView2）
- 调试：设置环境变量 `MEWALLPAPER_DEBUG=1` 开启 `/api/dev/eval`（发布版默认关闭）

## 目录结构

```
app/            Python 核心：主窗口、壁纸引擎、mpv 后端、Web API、Qt 对话框
  players/      libmpv-2.dll（mpv 官方 Windows 构建）
  ui/           Qt 界面组件（液态玻璃主题、取帧/裁剪对话框）
web/            WebView2 承载的前端 UI（原生 HTML/CSS/JS）
data/           运行数据：config.json、library.json、thumbs/（不入库、安装时不携带）
wallpapers/     自带壁纸目录（可放自己的壁纸，启动自动扫描）
scripts/        开发脚本（回归测试、截图、重启）
packaging/      PyInstaller + Inno Setup 打包脚本
```

## 技术架构

```
┌─ WebView2 窗口（web/index.html 浅色液态玻璃 UI）
│     │  HTTP 127.0.0.1:15216（仅本机）
├─ Flask API 线程（webapi.py：壁纸库/设置/在线源代理/下载）
│     │  bridge 队列 → GUI 线程
└─ Qt GUI 线程（PySide6：托盘、快捷键、轮播、mpv 视频壁纸嵌入 WorkerW）
```

- 视频壁纸：mpv (libmpv-2.dll) 渲染进原生 HWND，SetParent 挂到桌面 WorkerW 层；每 1.5s 层级保活防 Explorer 重绘盖掉
- 静态壁纸：SystemParametersInfoW + 注册表 WallpaperStyle
- 取帧/预览：mpv OpenGL 渲染（MpvRenderContext），预览窗口带系统标题栏，关闭自动恢复桌面壁纸

## 构建安装包

```bat
pip install pyinstaller
packaging\build.bat        :: PyInstaller 打 exe → Inno Setup 出 Setup.exe
```

产物：`packaging\output\MeWallpaper-Setup-<版本>.exe`

## 开源许可

本项目代码以 [MIT](LICENSE) 发布。用到的第三方组件及其许可证见 [licenses/THIRD-PARTY-LICENSES.md](licenses/THIRD-PARTY-LICENSES.md)（PySide6 以动态链接方式使用其 LGPL-3.0 授权，mpv 以动态加载方式使用其 LGPLv2.1+ 授权）。
