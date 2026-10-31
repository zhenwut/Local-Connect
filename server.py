"""Local phone-to-PC text and file transfer with JPG-to-PDF support."""

import argparse
import hmac
import ipaddress
import json
import os
import re
import secrets
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from photo_pdf import inspect_jpeg, write_pdf
from connection import ConnectionManager, qr_svg
from file_transfer import FileStore, MAX_FILE_BYTES
from receiver_lifecycle import ReceiverLifecycle
from pdf_workspace import PdfWorkspace
from pdf_convert import IMAGE_FORMATS, file_format, thumbnail_png
from storage_quota import DEFAULT_LIMIT_BYTES, StorageQuota


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
    def __init__(self, code, uploads_root, storage_limit_bytes=DEFAULT_LIMIT_BYTES):
        self.code = code
        self.text = ""
        self.phone_opened = False
        self.version = 0
        self.uploads_root = Path(uploads_root)
        self.quota = StorageQuota(self.uploads_root, storage_limit_bytes)
        self.files = FileStore(self.uploads_root, quota=self.quota)
        self.pdf_workspace = PdfWorkspace(self.files)
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

    def mark_phone_opened(self):
        with self.lock:
            self.phone_opened = True

    def phone_opened_status(self):
        with self.lock:
            return self.phone_opened

    def latest(self):
        with self.lock:
            return {
                "version": self.version,
                "text": self.text,
                **self._photo_status(),
                **self.files.status(),
                **self.pdf_workspace.status(),
            }

    def include_file_in_pdf(self, item):
        if item["preview_type"] != "image/jpeg" or item["bytes"] > MAX_PHOTO_BYTES:
            return False
        try:
            metadata = inspect_jpeg(item["path"].read_bytes())
        except (OSError, ValueError):
            return False
        with self.lock:
            if not self.files.get(item["id"]):
                return False
            if len(self.photos) >= MAX_PHOTOS or sum(p["bytes"] for p in self.photos) + item["bytes"] > MAX_BATCH_BYTES:
                return False
            width, height, orientation, colorspace = metadata
            self.photos.append({"name": item["name"], "path": item["path"], "bytes": item["bytes"],
                                "width": width, "height": height, "orientation": orientation, "colorspace": colorspace})
            self.photo_version += 1
            return True

    def add_photo(self, data, metadata):
        width, height, orientation, colorspace = metadata
        with self.lock:
            if len(self.photos) >= MAX_PHOTOS:
                raise ValueError(f"每次最多 {MAX_PHOTOS} 张照片，请重新打开电脑接收页后继续")
            if sum(photo["bytes"] for photo in self.photos) + len(data) > MAX_BATCH_BYTES:
                raise ValueError("本批照片总量不能超过 150 MiB")
            folder = self.uploads_root / self.batch_name
            name = f"{len(self.photos) + 1:03d}.jpg"
            path = folder / name
            temporary = folder / (name + ".part")
            ticket = self.quota.reserve(len(data))
            try:
                folder.mkdir(parents=True, exist_ok=True)
                temporary.write_bytes(data)
                self.quota.check(ticket)
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
                self.quota.release(ticket)
            self.photos.append({
                "name": name, "path": path, "width": width, "height": height,
                "orientation": orientation, "colorspace": colorspace, "bytes": len(data),
            })
            self.photo_version += 1
            return self._photo_status()

    def start_new_batch(self, clear_text=False):
        with self.lock:
            if clear_text:
                self.text = ""
                self.version += 1
            self.batch_name = self._new_batch_name()
            self.photos = []
            self.photo_version += 1
            self.pdf_version = 0
            with self.pdf_workspace.lock:
                self.files.new_batch()
                self.pdf_workspace.reset()
            return self._photo_status()

    def make_pdf(self):
        with self.lock:
            if not self.photos:
                raise ValueError("请先从手机上传 JPG 照片")
            folder = self.uploads_root / self.batch_name
            path = folder / "photos.pdf"
            if self.pdf_version != self.photo_version or not path.is_file():
                temporary = folder / "photos.pdf.part"
                old_bytes = path.stat().st_size if path.is_file() else 0
                ticket = self.quota.reserve(sum(photo['bytes'] for photo in self.photos) + 1024 * 1024,
                                            replace_bytes=old_bytes)
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                    write_pdf(self.photos, temporary)
                    self.quota.check(ticket, replace_bytes=old_bytes)
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
                    self.quota.release(ticket)
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

    def __init__(self, address, code, uploads_root=None, shared_server=None,
                 storage_limit_bytes=DEFAULT_LIMIT_BYTES):
        super().__init__(address, TransferHandler)
        self.hotspot_only = shared_server is not None
        self.state = shared_server.state if shared_server else TransferState(
            code, uploads_root or ROOT / "uploads", storage_limit_bytes)
        self.receiver_token = shared_server.receiver_token if shared_server else secrets.token_hex(32)
        self.connection = shared_server.connection if shared_server else None
        self.receiver_lifecycle = shared_server.receiver_lifecycle if shared_server else ReceiverLifecycle(
            lambda: self.state.start_new_batch(clear_text=True), self.shutdown,
        )

    def server_close(self):
        lifecycle = getattr(self, "receiver_lifecycle", None)
        if lifecycle and not self.hotspot_only:
            lifecycle.stopped.set()
        if hasattr(self, 'state') and not self.hotspot_only:
            self.state.pdf_workspace.close()
        super().server_close()


class HotspotPhoneListener:
    """Bind only the currently reported hotspot address; retry while Windows sets it up."""

    def __init__(self, local_server, code, port):
        self.local_server = local_server
        self.code = code
        self.port = port
        self.phone_server = None
        self.last_error = None
        self.last_attempted_ip = None
        self.first_error_at = None
        self.pending_reported = False

    def close(self):
        if self.phone_server:
            self.local_server.connection.set_listening_ip(None)
            self.phone_server.shutdown()
            self.phone_server.server_close()
            self.phone_server = None

    def refresh(self):
        connection = self.local_server.connection
        with connection.lock:
            hotspot = connection.hotspot.copy()
        ip = hotspot.get("ip") if hotspot.get("active") and hotspot.get("password") == connection.password else None
        if not ip:
            self.close()
            self.last_error = None
            self.last_attempted_ip = None
            self.first_error_at = None
            self.pending_reported = False
            return False
        if self.phone_server and self.phone_server.server_address[0] == ip:
            return False
        self.close()
        self.last_attempted_ip = ip
        try:
            candidate = TransferServer((ip, self.port), self.code, shared_server=self.local_server)
        except OSError as exc:
            self.last_error = exc
            if self.first_error_at is None:
                self.first_error_at = time.monotonic()
            return False
        self.phone_server = candidate
        connection.set_listening_ip(ip)
        self.last_error = None
        self.first_error_at = None
        self.pending_reported = False
        threading.Thread(target=candidate.serve_forever, daemon=True).start()
        return True


def log_bilingual(chinese, english):
    print(f"{chinese} / {english}", flush=True)


class TransferHandler(BaseHTTPRequestHandler):
    def _hotspot_access_allowed(self):
        if not self.server.hotspot_only:
            return True
        connection = self.server.connection
        snapshot = connection.snapshot() if connection else {}
        return snapshot.get("mode") in ("wifi", "web") and self.server.server_address[0] == connection.listening_ip

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

    def _file(self, path, content_type, name=None, inline=False):
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        disposition = "inline" if inline else "attachment"
        self.send_header("Content-Disposition", f"{disposition}; filename=\"download\"; filename*=UTF-8''{quote(name or path.name, safe='')}")
        self.send_header("Content-Security-Policy", "sandbox; default-src 'none'")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                self.wfile.write(chunk)

    def _is_local(self):
        return is_loopback(self.client_address[0])

    def _host_allowed(self):
        hosts = self.headers.get_all('Host', [])
        if len(hosts) != 1:
            return False
        host = hosts[0].lower()
        port = self.server.server_port
        if self.server.hotspot_only:
            allowed = {f'{self.server.server_address[0]}:{port}'}
            if port == 80:
                allowed.add(self.server.server_address[0])
            return host in allowed
        allowed = {f'localhost:{port}', f'127.0.0.1:{port}'}
        if port == 80:
            allowed.update(('localhost', '127.0.0.1'))
        return host in allowed

    def _receiver_local(self):
        origin = self.headers.get("Origin")
        expected_origin = 'http://' + self.headers.get('Host', '')
        if (not self._is_local() or not self._host_allowed()
                or self.headers.get("Sec-Fetch-Site") == "cross-site"
                or (origin is not None and origin.lower() != expected_origin.lower())):
            self._json(403, {"error": "只能由电脑本机接收页控制服务"})
            return False
        return True

    def _receiver_token_valid(self, payload):
        token = payload.get('receiver_token')
        if not isinstance(token, str) or not hmac.compare_digest(token, self.server.receiver_token):
            self._json(403, {'error': '接收页令牌无效，请刷新电脑页面'})
            return False
        return True

    def _receiver_action(self, action):
        if not self._receiver_local():
            return
        payload = self._read_json(1024)
        if payload is None:
            return
        if not self._receiver_token_valid(payload):
            return
        page_id = payload.get("page_id")
        if not isinstance(page_id, str) or not re.fullmatch(r"[a-f0-9]{32}", page_id):
            self._json(400, {"error": "无效的页面标识"})
            return
        lifecycle = self.server.receiver_lifecycle
        if action == "open":
            if not lifecycle.open(page_id):
                self._json(409, {"error": "服务正在关闭，请重新启动 Local Connect"})
                return
        else:
            lifecycle.close(page_id)
        self._json(200, {"ok": True, "instance_id": lifecycle.instance_id})

    def _receiver_stream(self):
        if not self._receiver_local():
            return
        page_id = parse_qs(urlsplit(self.path).query).get("page_id", [""])[0]
        lifecycle = self.server.receiver_lifecycle
        stream_id = lifecycle.connect(page_id)
        if stream_id is None:
            self._json(404, {"error": "接收页尚未注册或服务正在关闭"})
            return
        try:
            self.connection.settimeout(5)
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            while lifecycle.is_connected(page_id, stream_id) and not lifecycle.stopped.is_set():
                self.wfile.write(b"event: heartbeat\ndata: {}\n\n")
                self.wfile.flush()
                if lifecycle.stopped.wait(2):
                    break
        except (OSError, ConnectionError):
            pass
        finally:
            lifecycle.disconnect(page_id, stream_id)

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
        if not self._hotspot_access_allowed():
            self._json(503, {"error": "电脑热点已断开"})
            return
        if not self._host_allowed():
            self._json(403, {'error': '请求地址无效'})
            return
        path = urlsplit(self.path).path
        if path == "/":
            self._page("phone.html")
        elif path in ("/files-ui.js", "/files-ui.css", "/pdf-ui.js", "/i18n.js"):
            mime = "text/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8"
            self._send(200, (ROOT / path[1:]).read_bytes(), mime)
        elif path == "/receiver":
            if not self._is_local():
                self._json(403, {"error": "接收页只能在电脑本机打开"})
                return
            self._page("receiver.html")
        elif path == "/api/latest":
            if not self._is_local():
                self._json(403, {"error": "只能在电脑本机读取文本"})
                return
            self._json(200, {**self.server.state.latest(), "instance_id": self.server.receiver_lifecycle.instance_id})
        elif path == "/api/receiver/events":
            self._receiver_stream()
        elif path == '/api/receiver/token':
            if not self._receiver_local():
                return
            self._json(200, {'receiver_token': self.server.receiver_token})
        elif path == "/api/connect":
            if not self._is_local():
                self._json(403, {"error": "连接信息只能在电脑本机查看"})
                return
            connection = self.server.connection
            details = connection.snapshot() if connection else {"mode": "manual", "code": self.server.state.code}
            self._json(200, {**details, "phone_opened": self.server.state.phone_opened_status()})
        elif path == "/api/connect/qr":
            if not self._is_local():
                self._json(403, {"error": "二维码只能在电脑本机查看"})
                return
            snapshot = self.server.connection.snapshot() if self.server.connection else {}
            kind = urlsplit(self.path).query
            value = snapshot.get("wifi_qr" if kind == "wifi" else "web_qr") if kind in ("wifi", "web") else None
            if not value:
                self._json(404, {"error": "当前二维码不可用"})
                return
            self._send(200, qr_svg(value), "image/svg+xml")
        elif path.startswith("/api/exports/"):
            if not self._receiver_local():
                return
            parts = path.removeprefix('/api/exports/').split('/')
            job = self.server.state.pdf_workspace.get_job(parts[0], include_path=True)
            if not job or len(parts) > 2 or (len(parts) == 2 and parts[1] != 'download'):
                self._json(404, {'error': '下载记录已过期'})
            elif len(parts) == 1:
                self._json(200, {k: v for k, v in job.items() if k != 'path'})
            elif job['state'] != 'ready':
                self._json(409, {'error': job['message']})
            else:
                mime = 'application/zip' if job['name'].endswith('.zip') else 'application/pdf'
                self._file(job['path'], mime, job['name'])
        elif path.startswith("/api/files/"):
            if not self._is_local():
                self._json(403, {"error": "只能在电脑本机预览和下载文件"})
                return
            parts = path.removeprefix("/api/files/").split("/")
            preview = len(parts) == 2 and parts[1] == "preview"
            thumbnail = len(parts) == 2 and parts[1] == 'thumbnail'
            item = self.server.state.files.get(parts[0]) if len(parts) == 1 or preview or thumbnail else None
            if not item or (preview and not item["preview_type"]) or not item["path"].is_file():
                self._json(404, {"error": "文件或预览不存在"})
                return
            if thumbnail:
                if file_format(item['name']) not in IMAGE_FORMATS:
                    self._json(404, {'error': '此文件没有图片缩略图'})
                    return
                target = self.server.state.uploads_root / '.thumbnails' / (item['id'] + '.png')
                try:
                    if not target.is_file():
                        data = thumbnail_png(item['path'])
                        ticket = self.server.state.quota.reserve(len(data))
                        temporary = target.with_name(item['id'] + '-' + secrets.token_hex(6) + '.part')
                        try:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            temporary.write_bytes(data)
                            self.server.state.quota.check(ticket)
                            os.replace(temporary, target)
                        finally:
                            temporary.unlink(missing_ok=True)
                            self.server.state.quota.release(ticket)
                    self._file(target, 'image/png', item['name'] + '.png', True)
                except (OSError, ValueError):
                    self._json(404, {'error': '无法读取图片缩略图'})
                return
            self._file(item["path"], item["preview_type"] if preview else "application/octet-stream", item["name"], preview)
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
        if not self._hotspot_access_allowed():
            self._json(503, {"error": "电脑热点已断开"})
            return
        if not self._host_allowed():
            self._json(403, {'error': '请求地址无效'})
            return
        path = urlsplit(self.path).path
        if path == "/api/send":
            self._receive_text()
        elif path == "/api/connect/arrived":
            payload = self._read_json(1024)
            if payload is None:
                return
            code = payload.get("code")
            if not isinstance(code, str) or not hmac.compare_digest(code.upper(), self.server.state.code):
                self._json(403, {"error": "访问码无效"})
                return
            self.server.state.mark_phone_opened()
            self._json(200, {"ok": True})
        elif path in ("/api/receiver/open", "/api/receiver/close"):
            self._receiver_action(path.rsplit("/", 1)[-1])
        elif path == "/api/files":
            self._receive_file()
        elif path in ('/api/pdf-containers', '/api/exports'):
            if not self._receiver_local():
                return
            payload = self._read_json(32 * 1024)
            if payload is None:
                return
            if not self._receiver_token_valid(payload):
                return
            try:
                workspace = self.server.state.pdf_workspace
                result = workspace.action(payload) if path == '/api/pdf-containers' else workspace.start_export(payload)
                self._json(200, result)
            except ValueError as error:
                self._json(400, {'error': str(error)})
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

    def _receive_file(self):
        code = self.headers.get("X-Access-Code", "").strip().upper()
        if not code.isascii() or not hmac.compare_digest(code, self.server.state.code):
            self._json(403, {"error": "访问码不正确"})
            return
        if self.headers.get("Transfer-Encoding"):
            self._json(400, {"error": "上传需要明确的文件长度"})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._json(411, {"error": "缺少有效的文件长度"})
            return
        if length < 0 or length > MAX_FILE_BYTES:
            self._json(413, {"error": "单个文件不能超过 2 GiB"})
            return
        try:
            name = unquote(self.headers.get("X-File-Name", ""), encoding="utf-8", errors="strict")
            if not name:
                raise ValueError("请提供文件名")
            self.connection.settimeout(120)
            item = self.server.state.files.receive(self.rfile, length, name)
        except (ValueError, UnicodeError) as error:
            self._json(400, {"error": str(error)})
            return
        except OSError:
            self._json(500, {"error": "上传中断或保存失败，请检查网络和电脑剩余空间后重试"})
            return
        pdf_included = self.server.state.include_file_in_pdf(item)
        self._json(200, {"ok": True, "id": item["id"], "name": item["name"], "pdf_included": pdf_included})

    def _make_pdf(self):
        if not self._receiver_local():
            return
        payload = self._read_json(1024)
        if payload is None or not self._receiver_token_valid(payload):
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
        if not self._receiver_local():
            return
        payload = self._read_json(1024)
        if payload is None or not self._receiver_token_valid(payload):
            return
        self._json(200, {"ok": True, **self.server.state.start_new_batch()})

def main():
    parser = argparse.ArgumentParser(description="Local Connect：手机向电脑发送文本和文件")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    parser.add_argument("--open-browser", action="store_true", help="启动后打开电脑接收页")
    parser.add_argument('--storage-limit-gib', type=int, default=20,
                        help='Local Connect 传输文件的全局空间上限，默认 20 GiB；不会自动删除文件')
    args = parser.parse_args()

    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    try:
        if args.storage_limit_gib < 1:
            parser.error('storage-limit-gib 必须至少为 1')
        server = TransferServer(("127.0.0.1", args.port), code,
                                storage_limit_bytes=args.storage_limit_gib * 1024 ** 3)
    except OSError as exc:
        parser.exit(1, f"无法启动服务 / Cannot start service: {exc}\n")

    port = server.server_address[1]
    server.connection = ConnectionManager(code, port, None)
    listener = HotspotPhoneListener(server, code, port)
    listener.refresh()
    listener_stop = threading.Event()

    def update_phone_listener():
        while not listener_stop.wait(2):
            if listener.refresh():
                ready = server.connection.snapshot()
                log_bilingual(f"手机入口已就绪：{ready['web_url']}", f"Phone endpoint ready: {ready['web_url']}")
            elif (listener.last_error and listener.first_error_at is not None
                  and not listener.pending_reported and time.monotonic() - listener.first_error_at >= 15):
                log_bilingual(f"热点地址 {listener.last_attempted_ip} 暂不可监听，仍在重试：{listener.last_error}",
                              f"Hotspot address {listener.last_attempted_ip} is not ready; retrying: {listener.last_error}")
                listener.pending_reported = True

    connection = server.connection.snapshot()
    log_bilingual(f"电脑接收页：http://localhost:{port}/receiver", f"Receiver: http://localhost:{port}/receiver")
    if connection["mode"] in ("wifi", "web"):
        log_bilingual(f"手机发送页：{connection['web_url']}", f"Phone page: {connection['web_url']}")
    log_bilingual(f"本次访问码：{code}", f"Session access code: {code}")
    if connection["mode"] == "wifi":
        log_bilingual(f"Windows 热点已开启：{connection['ssid']}；请在电脑接收页扫描二维码。",
                      f"Windows hotspot is on: {connection['ssid']}. Scan the QR codes on the receiver page.")
    elif connection["mode"] == "web":
        log_bilingual("Windows 热点已有设备连接；请在电脑接收页扫描网页二维码。",
                      "A device has joined the hotspot. Scan the web QR code on the receiver page.")
    else:
        if connection.get("reason") == "hotspot_address_missing":
            log_bilingual("热点已开启，正在获取 IPv4 地址；手机入口尚未开放。",
                          "Hotspot is on; waiting for its IPv4 address. The phone endpoint is not open yet.")
        elif connection.get("reason") == "hotspot_listener_pending":
            log_bilingual("热点已开启，正在等待手机入口就绪；将自动重试。",
                          "Hotspot is on; waiting for the phone endpoint. Retrying automatically.")
        else:
            log_bilingual("热点不可用；手机入口不会在其他网络开放。",
                          "Hotspot unavailable. The phone endpoint will not open on other networks.")
            if connection.get("reason"):
                log_bilingual(f"热点诊断：{connection['reason']}", f"Hotspot diagnostic: {connection['reason']}")
    log_bilingual("按 Ctrl+C 停止服务。", "Press Ctrl+C to stop the service.")
    log_bilingual("关闭所有电脑接收页约 8 秒后，服务停止并尝试恢复热点原有状态。",
                  "The service stops about 8 seconds after all receiver pages close and tries to restore the prior hotspot state.")
    update_thread = threading.Thread(target=update_phone_listener, daemon=True)
    update_thread.start()
    server.receiver_lifecycle.start()
    browser_timer = None
    if args.open_browser:
        browser_timer = threading.Timer(0.5, webbrowser.open, args=(f"http://localhost:{port}/receiver",))
        browser_timer.daemon = True
        browser_timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log_bilingual("服务已停止。", "Service stopped.")
    finally:
        if browser_timer is not None:
            browser_timer.cancel()
        listener_stop.set()
        update_thread.join(timeout=3)
        listener.close()
        server.server_close()
        server.connection.close(stop_active_hotspot=server.receiver_lifecycle.closing)


if __name__ == "__main__":
    main()
