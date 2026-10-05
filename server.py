"""A small, dependency-free phone-to-PC text and photo transfer server."""

import argparse
import hmac
import ipaddress
import json
import os
import secrets
import socket
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from photo_pdf import inspect_jpeg, write_pdf


ROOT = Path(__file__).resolve().parent
MAX_TEXT_BYTES = 64 * 1024
MAX_REQUEST_BYTES = MAX_TEXT_BYTES + 4096
MAX_PHOTO_BYTES = 20 * 1024 * 1024
MAX_BATCH_BYTES = 150 * 1024 * 1024
MAX_PHOTOS = 30
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def is_loopback(address):
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


class TransferState:
    def __init__(self, code, uploads_root):
        self.code = code
        self.text = ""
        self.version = 0
        self.uploads_root = Path(uploads_root)
        self.batch_name = self._new_batch_name()
        self.photos = []
        self.photo_version = 0
        self.pdf_version = 0
        self.lock = threading.Lock()

    @staticmethod
    def _new_batch_name():
        return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)

    def _photo_status(self):
        return {
            "photo_version": self.photo_version,
            "photos": [
                {key: photo[key] for key in ("name", "width", "height", "bytes")}
                for photo in self.photos
            ],
            "photo_folder": f"uploads/{self.batch_name}" if self.photos else "",
            "pdf_ready": bool(self.photos and self.pdf_version == self.photo_version),
        }

    def update(self, text):
        with self.lock:
            self.text = text
            self.version += 1
            return self.version

    def latest(self):
        with self.lock:
            return {
                "version": self.version,
                "text": self.text,
                **self._photo_status(),
            }

    def add_photo(self, data, metadata):
        width, height, orientation, colorspace = metadata
        with self.lock:
            if len(self.photos) >= MAX_PHOTOS:
                raise ValueError(f"每批最多 {MAX_PHOTOS} 张照片，请在电脑上开始新批次")
            if sum(photo["bytes"] for photo in self.photos) + len(data) > MAX_BATCH_BYTES:
                raise ValueError("本批照片总量不能超过 150 MiB")
            folder = self.uploads_root / self.batch_name
            folder.mkdir(parents=True, exist_ok=True)
            name = f"{len(self.photos) + 1:03d}.jpg"
            path = folder / name
            temporary = folder / (name + ".part")
            try:
                temporary.write_bytes(data)
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            self.photos.append({
                "name": name, "path": path, "width": width, "height": height,
                "orientation": orientation, "colorspace": colorspace, "bytes": len(data),
            })
            self.photo_version += 1
            return self._photo_status()

    def start_new_batch(self):
        with self.lock:
            self.batch_name = self._new_batch_name()
            self.photos = []
            self.photo_version += 1
            self.pdf_version = 0
            return self._photo_status()

    def make_pdf(self):
        with self.lock:
            if not self.photos:
                raise ValueError("请先从手机上传 JPG 照片")
            folder = self.uploads_root / self.batch_name
            path = folder / "photos.pdf"
            if self.pdf_version != self.photo_version or not path.is_file():
                temporary = folder / "photos.pdf.part"
                try:
                    write_pdf(self.photos, temporary)
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
                self.pdf_version = self.photo_version
            return self._photo_status()

    def photo_path(self, index):
        with self.lock:
            if index < 1 or index > len(self.photos):
                return None
            return self.photos[index - 1]["path"]

    def pdf_path(self):
        with self.lock:
            if not self.photos or self.pdf_version != self.photo_version:
                return None
            path = self.uploads_root / self.batch_name / "photos.pdf"
            return path if path.is_file() else None


class TransferServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, code, uploads_root=None):
        super().__init__(address, TransferHandler)
        self.state = TransferState(code, uploads_root or ROOT / "uploads")


class TransferHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Text and access codes should not end up in terminal logs.
        pass

    def _send(self, status, data, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, data, "application/json; charset=utf-8")

    def _page(self, name):
        data = (ROOT / name).read_bytes()
        self._send(200, data, "text/html; charset=utf-8")

    def _file(self, path, content_type):
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                self.wfile.write(chunk)

    def _is_local(self):
        return is_loopback(self.client_address[0])

    def _read_json(self, max_bytes):
        if self.headers.get_content_type() != "application/json":
            self._json(415, {"error": "请发送 JSON 数据"})
            return None
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._json(411, {"error": "缺少有效的数据长度"})
            return None
        if length < 1 or length > max_bytes:
            self._json(413, {"error": "文本过长或请求为空"})
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"error": "数据格式有误"})
            return None
        if not isinstance(payload, dict):
            self._json(400, {"error": "数据格式有误"})
            return None
        return payload

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            self._page("phone.html")
        elif path == "/receiver":
            if not self._is_local():
                self._json(403, {"error": "接收页只能在电脑本机打开"})
                return
            self._page("receiver.html")
        elif path == "/api/latest":
            if not self._is_local():
                self._json(403, {"error": "只能在电脑本机读取文本"})
                return
            self._json(200, self.server.state.latest())
        elif path == "/api/photos/pdf":
            if not self._is_local():
                self._json(403, {"error": "只能在电脑本机下载 PDF"})
                return
            pdf_path = self.server.state.pdf_path()
            if pdf_path is None:
                self._json(404, {"error": "请先生成 PDF"})
                return
            self._file(pdf_path, "application/pdf")
        elif path.startswith("/api/photos/"):
            if not self._is_local():
                self._json(403, {"error": "只能在电脑本机下载照片"})
                return
            index = path.removeprefix("/api/photos/")
            photo_path = self.server.state.photo_path(int(index)) if index.isdecimal() else None
            if photo_path is None:
                self._json(404, {"error": "照片不存在"})
                return
            self._file(photo_path, "image/jpeg")
        else:
            self._json(404, {"error": "页面不存在"})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/send":
            self._receive_text()
        elif path == "/api/photos":
            self._receive_photo()
        elif path == "/api/photos/pdf":
            self._make_pdf()
        elif path == "/api/photos/new":
            self._new_photo_batch()
        else:
            self._json(404, {"error": "接口不存在"})

    def _receive_text(self):
        payload = self._read_json(MAX_REQUEST_BYTES)
        if payload is None:
            return

        code = payload.get("code")
        text = payload.get("text")
        if not isinstance(code, str) or not hmac.compare_digest(
            code.strip().upper(), self.server.state.code
        ):
            self._json(403, {"error": "访问码不正确"})
            return
        if not isinstance(text, str) or not text:
            self._json(400, {"error": "请输入文本"})
            return
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            self._json(413, {"error": "文本不能超过 64 KiB"})
            return

        version = self.server.state.update(text)
        self._json(200, {"ok": True, "version": version})

    def _receive_photo(self):
        code = self.headers.get("X-Access-Code", "")
        if not hmac.compare_digest(code.strip().upper(), self.server.state.code):
            self._json(403, {"error": "访问码不正确"})
            return
        if self.headers.get_content_type() != "image/jpeg":
            self._json(415, {"error": "只支持 JPG 照片"})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._json(411, {"error": "缺少有效的文件长度"})
            return
        if length < 1 or length > MAX_PHOTO_BYTES:
            self._json(413, {"error": "单张 JPG 不能超过 20 MiB"})
            return
        data = self.rfile.read(length)
        if len(data) != length:
            self._json(400, {"error": "照片传输不完整"})
            return
        try:
            metadata = inspect_jpeg(data)
            status = self.server.state.add_photo(data, metadata)
        except ValueError as error:
            self._json(400, {"error": str(error)})
            return
        except OSError:
            self._json(500, {"error": "保存照片失败，请检查电脑磁盘"})
            return
        self._json(200, {"ok": True, **status})

    def _make_pdf(self):
        if not self._is_local():
            self._json(403, {"error": "只能在电脑本机生成 PDF"})
            return
        try:
            status = self.server.state.make_pdf()
        except ValueError as error:
            self._json(400, {"error": str(error)})
            return
        except OSError:
            self._json(500, {"error": "生成 PDF 失败，请检查电脑磁盘"})
            return
        self._json(200, {"ok": True, **status})

    def _new_photo_batch(self):
        if not self._is_local():
            self._json(403, {"error": "只能在电脑本机开始新批次"})
            return
        self._json(200, {"ok": True, **self.server.state.start_new_batch()})

def detect_lan_ip():
    # A UDP connect selects a route without sending a packet.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            address = sock.getsockname()[0]
            if not ipaddress.ip_address(address).is_loopback:
                return address
    except OSError:
        pass
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = item[4][0]
            if not ipaddress.ip_address(address).is_loopback:
                return address
    except OSError:
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description="Local Connect：手机向电脑发送文本和照片")
    parser.add_argument("--port", type=int, default=8766, help="监听端口，默认 8766")
    parser.add_argument("--lan-ip", help="手动指定终端中显示的电脑局域网 IPv4 地址")
    args = parser.parse_args()
    if args.lan_ip:
        try:
            ipaddress.IPv4Address(args.lan_ip)
        except ipaddress.AddressValueError:
            parser.error("--lan-ip 必须是 IPv4 地址")

    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    try:
        server = TransferServer(("0.0.0.0", args.port), code)
    except OSError as exc:
        parser.exit(1, f"无法启动服务：{exc}\n")

    port = server.server_address[1]
    lan_ip = args.lan_ip or detect_lan_ip()
    print(f"电脑接收页：http://localhost:{port}/receiver")
    if lan_ip:
        print(f"手机发送页：http://{lan_ip}:{port}/")
    else:
        print("未能自动找到局域网地址；请运行 ipconfig 查看 IPv4 地址。")
        print(f"手机发送页：http://<电脑的 IPv4 地址>:{port}/")
    print(f"本次访问码：{code}")
    print("按 Ctrl+C 停止服务。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
