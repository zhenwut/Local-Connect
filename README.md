# Local Connect

[简体中文](README.md) · [English](README.en.md)

用电脑热点在手机和电脑之间传送文本、任意格式文件，并在电脑上整理和导出 PDF。手机只需浏览器；传输和转换均在本地完成，无需账号、云端或中转服务器。

## 功能亮点

- **两步扫码连接**：启动时尝试开启 Windows 移动热点，生成随机强密码；第一码加入热点，第二码打开手机网页并填入本次访问码。电脑页用时间线显示进度。
- **文本与任意文件**：手机选中文件后自动逐个上传，支持多选、追加、进度及失败重试；文本显示字符数，电脑端可一键复制。TXT、CSV、EPUB 等均按原始字节传输。
- **直观接收与下载**：电脑端按文件展示名称、大小和格式图标；常见图片直接预览，点击卡片下载原文件。支持勾选下载或一键打包 ZIP。
- **PDF 工作区**：把同格式文件拖入可重命名的容器，调整图片顺序和 90° 旋转，按容器下载 PDF；文件可拖出，ZIP 会用容器 PDF 替代其中的原文件。
- **即开即用的界面**：电脑宽屏左右分栏、手机纵向布局；页面可切换中英文。刷新接收页清空当前记录；关闭所有电脑接收页约 8 秒后停止服务，随后尝试恢复热点原有状态。

## 开始使用

电脑需要 Python 3.10+（含 pip），手机连接需要可用的 Windows 移动热点。双击 [`start_local_connect.cmd`](start_local_connect.cmd)：脚本会检查并安装缺失依赖、启动服务、打开电脑接收页。也可在项目目录用一行 PowerShell 命令启动：

```powershell
py -3 run_local_connect.py
```

两种方式都会打开 `http://localhost:8766/receiver`；依次用手机扫描两个二维码。部分手机需在加入无互联网的热点时选择“保持连接”。用 `py -3 run_local_connect.py --port 9000` 可更改端口；按 `Ctrl+C` 停止服务。

代码同步到 GitHub 后，可在 PowerShell 一行克隆并运行（需 Git、Python 3.10+ 和网络；仓库仍为私有时还需访问权限）：

```powershell
git clone https://github.com/zhenwut/local-connect.git; if ($LASTEXITCODE -eq 0) { Set-Location local-connect; py -3 run_local_connect.py }
```

热点不可用时，手机入口不会开放到其他局域网。如果第二个二维码打开超时，可在管理员 PowerShell 中运行一次：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup_hotspot_firewall.ps1
```

默认端口为 `8766`；更改端口时，防火墙脚本也需传入对应的 `-Port`。`python server.py` 仅供手动启动，不负责安装依赖或打开网页。

## 格式与限制

| 用途 | 支持范围 |
| --- | --- |
| 原样传输、下载、ZIP | 任意格式，包括 TXT、CSV/TSV、EPUB、图片、音视频、Office、压缩包和未知扩展名。 |
| 转换或合并 PDF | JPG/JPEG/JFIF、PNG、BMP、GIF、WebP、AVIF、TIF/TIFF、PDF；DOC/DOCX、XLS/XLSX、PPT/PPTX 需安装 Microsoft Office；HTML/HTM 需安装 Chrome 或 Edge。 |

TXT、CSV、EPUB 等可以传输，但目前不能放入 PDF 容器转换。PDF 容器只接受同格式文件；每个容器最多 500 MiB、500 页，单张图片最多 4000 万像素，HTML 文件最多 20 MiB。

文本每条最多 64 KiB；文件每个最多 2 GiB，每批最多 100 个、合计 10 GiB。`uploads/` 中的传输文件与生成的 PDF、ZIP、缩略图共用默认 20 GiB 空间上限，并保留至少 512 MiB 磁盘空闲；可用 `py -3 run_local_connect.py --storage-limit-gib 30` 调整。**达到上限只会拒绝新写入，不会自动删除文件，也不处理 `uploads/` 之外的本地文件。**刷新页面或重启服务只清空当前列表，旧文件仍留在 `uploads/`。

## 安全边界

每次启动重新生成热点密码、访问码和电脑接收页令牌；电脑入口只监听本机，手机入口只监听当前热点地址，并校验请求地址。热点提供 Wi-Fi 链路保护，但网页仍用 HTTP，**没有独立的 TLS 端到端加密**；不要把热点密码或二维码分享给不可信设备。

服务结束时会尝试恢复启动前的热点名称、密码和开关状态。

## 验证

```powershell
python -m unittest discover -s tests
node tests/browser_smoke.cjs
```

浏览器测试需要 Chrome 和 Node.js，使用临时服务，不会开启热点；真实扫码和 Windows 热点需在设备上验证。二维码使用内置 [Segno](https://github.com/heuer/segno)，许可证见 [`qr_lib/SEGNO-LICENSE.txt`](qr_lib/SEGNO-LICENSE.txt)。
