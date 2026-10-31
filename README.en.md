# Local Connect

[简体中文](README.md) · [English](README.en.md)

Transfer text and files of any type between a phone and a computer over the computer's hotspot, then organize and export PDFs on the computer. The phone only needs a browser. Transfers and conversions stay local, with no account, cloud storage, or relay server.

## Highlights

- **Two QR codes to connect:** On launch, Local Connect attempts to start Windows Mobile Hotspot with a new strong password. The first code joins the hotspot; the second opens the phone page and fills in the session access code. A timeline on the computer shows progress.
- **Text and any file type:** Selecting files on the phone starts sequential uploads. Multi-select, adding more files, progress, and retry are supported. Both pages show text character counts, and the computer can copy received text. TXT, CSV, EPUB, and other files retain their original bytes.
- **Clear downloads:** Each received file has a card with its name, size, and format icon. Common images have previews; click a card to download the original. Select files for a ZIP or download everything at once.
- **PDF workspace:** Drag files of the same format into a renameable container, reorder and rotate images in 90° steps, and download the resulting PDF. Files can be dragged back out. ZIP exports include a container's PDF in place of its source files.
- **Ready-to-use interface:** The desktop view uses side-by-side panels; the phone view is vertical. Pages can switch between Chinese and English. Refreshing the receiver clears its current list; closing all computer receiver tabs stops the service after about eight seconds, then attempts to restore the prior hotspot state.

## Get started

The computer needs Python 3.10+ with pip; phone access requires a working Windows Mobile Hotspot. Double-click [`start_local_connect.cmd`](start_local_connect.cmd) to check and install missing dependencies, start the service, and open the receiver page. Or run one PowerShell command in the project directory:

```powershell
py -3 run_local_connect.py
```

Either way, `http://localhost:8000/receiver` opens automatically. Scan both QR codes with the phone. If the phone warns that the hotspot has no internet, choose to stay connected. Use `py -3 run_local_connect.py --port 9000` for another port; press `Ctrl+C` to stop.

Once these changes are synced to GitHub, clone and run with one PowerShell line (requires Git, Python 3.10+, and network access; a private repository also requires access):

```powershell
git clone https://github.com/zhenwut/local-connect.git; if ($LASTEXITCODE -eq 0) { Set-Location local-connect; py -3 run_local_connect.py }
```

If the hotspot is unavailable, the phone endpoint does not open on another LAN. If the second QR code times out, or your firewall was configured only for the former port 8766, run this once in an administrator PowerShell window:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup_hotspot_firewall.ps1
```

The default port is `8000`. Pass the matching `-Port` to the firewall script when changing it. `python server.py` is a manual start command; it does not install dependencies or open a browser.

## Formats and limits

| Use | Supported formats |
| --- | --- |
| Original upload, download, and ZIP | Any file type, including TXT, CSV/TSV, EPUB, images, audio, video, Office documents, archives, and unknown extensions. |
| PDF conversion or merging | JPG/JPEG/JFIF, PNG, BMP, GIF, WebP, AVIF, TIF/TIFF, and PDF; DOC/DOCX, XLS/XLSX, and PPT/PPTX require Microsoft Office; HTML/HTM requires Chrome or Edge. |

TXT, CSV, and EPUB can be transferred but cannot currently be converted in a PDF container. A container accepts only one file format and is limited to 500 MiB and 500 pages. An image can be at most 40 million pixels; an HTML source can be at most 20 MiB.

Text is limited to 64 KiB per message. Files are limited to 2 GiB each, 100 files and 10 GiB per batch. Transfers and generated PDFs, ZIPs, and thumbnails in `uploads/` share a default 20 GiB storage limit, with at least 512 MiB of disk space kept free. Change the limit with `py -3 run_local_connect.py --storage-limit-gib 30`. **Reaching the limit blocks new writes; it never automatically deletes files or changes local files outside `uploads/`.** Refreshing the page or restarting the service clears the current list, while older files remain in `uploads/`.

## Security boundary

Each launch creates a new hotspot password, access code, and computer receiver token. The computer endpoint listens only on loopback; the phone endpoint listens only on the current hotspot address. Requests are checked against the expected host. The hotspot protects the Wi-Fi link, but the web page still uses HTTP **without separate end-to-end TLS encryption**. Do not share the hotspot password or QR codes with untrusted devices.

On exit, the service attempts to restore the hotspot's previous name, password, and on/off state.

## Verify

```powershell
python -m unittest discover -s tests
node tests/browser_smoke.cjs
```

The browser test needs Chrome and Node.js. It uses an isolated server and does not start the hotspot; test the real QR flow and Windows hotspot on your devices. QR codes use the bundled [Segno](https://github.com/heuer/segno); see [`qr_lib/SEGNO-LICENSE.txt`](qr_lib/SEGNO-LICENSE.txt).
