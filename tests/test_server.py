import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import quote

from server import MAX_TEXT_BYTES, TransferServer, is_loopback


class TransferServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.uploads_dir = tempfile.TemporaryDirectory()
        cls.server = TransferServer(
            ("127.0.0.1", 0), "ABCD2345",
            uploads_root=cls.uploads_dir.name,
        )
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.uploads_dir.cleanup()

    def setUp(self):
        with self.server.state.lock:
            self.server.state.text = ""
            self.server.state.version = 0
            self.server.state.phone_opened = False
        self.server.state.start_new_batch()

    def request(self, path, payload=None):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urlopen(request) as response:
                return response.status, response.read()
        except HTTPError as error:
            with error:
                return error.code, error.read()

    def upload(self, data, code="ABCD2345", content_type="image/jpeg"):
        request = Request(
            self.base + "/api/photos",
            data=data,
            headers={"Content-Type": content_type, "X-Access-Code": code},
        )
        try:
            with urlopen(request) as response:
                return response.status, response.read()
        except HTTPError as error:
            with error:
                return error.code, error.read()

    def test_send_and_keep_only_latest_text(self):
        for text in ("第一条\n第二行", "最新的文本"):
            status, body = self.request("/api/send", {"code": "abcd2345", "text": text})
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["ok"])
        status, body = self.request("/api/latest")
        self.assertEqual(status, 200)
        latest = json.loads(body)
        self.assertEqual(
            {key: latest[key] for key in ("version", "text")},
            {"version": 2, "text": "最新的文本"},
        )
        self.assertEqual(latest["photos"], [])

    def test_open_receiver_clears_records_without_deleting_files(self):
        first_page = "a" * 32
        second_page = "b" * 32
        self.request("/api/receiver/open", {"page_id": first_page})
        self.send_file("saved.txt", b"keep on disk")
        saved = self.server.state.files.status()["files"][0]
        saved_path = self.server.state.files.get(saved["id"])["path"]
        self.request("/api/send", {"code": "ABCD2345", "text": "old record"})
        self.request("/api/receiver/open", {"page_id": first_page})
        self.assertEqual(self.server.state.latest()["text"], "old record")
        status, body = self.request("/api/receiver/open", {"page_id": second_page})
        self.assertEqual(status, 200)
        self.assertIn("instance_id", json.loads(body))
        latest = self.server.state.latest()
        self.assertEqual(latest["text"], "")
        self.assertEqual(latest["files"], [])
        self.assertEqual(saved_path.read_bytes(), b"keep on disk")
        for page in (first_page, second_page):
            self.request("/api/receiver/close", {"page_id": page})

    def test_receiver_controls_reject_remote_or_cross_origin_requests(self):
        payload = {"page_id": "c" * 32}
        with patch("server.is_loopback", return_value=False):
            self.assertEqual(self.request("/api/receiver/open", payload)[0], 403)
            self.assertEqual(self.request("/api/receiver/close", payload)[0], 403)
            self.assertEqual(self.request("/api/receiver/events?page_id=" + payload["page_id"])[0], 403)
        request = Request(self.base + "/api/receiver/open", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json", "Origin": "https://example.com"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        error.exception.close()

    def test_prompt_conversion_endpoint_is_absent(self):
        status, body = self.request("/api/convert", {"version": 1})
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "接口不存在")

    def test_reject_invalid_code_empty_and_oversized_text(self):
        cases = [
            ({"code": "wrong", "text": "hello"}, 403),
            ({"code": "ABCD2345", "text": ""}, 400),
            ({"code": "ABCD2345", "text": "a" * (MAX_TEXT_BYTES + 1)}, 413),
        ]
        for payload, expected_status in cases:
            with self.subTest(expected_status=expected_status):
                status, _ = self.request("/api/send", payload)
                self.assertEqual(status, expected_status)
        self.assertEqual(self.server.state.latest()["version"], 0)

    def test_pages_and_loopback_check(self):
        for path in ("/", "/receiver"):
            status, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertIn(b"<!doctype html>", body)
        self.assertTrue(is_loopback("127.0.0.1"))
        self.assertFalse(is_loopback("192.168.1.2"))

    def test_connection_qr_is_only_available_on_pc(self):
        self.server.connection = Mock()
        self.server.connection.snapshot.return_value = {
            "mode": "web", "code": "ABCD2345",
            "web_qr": "http://192.168.137.1:8766/#code=ABCD2345",
        }
        try:
            status, body = self.request("/api/connect")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["mode"], "web")
            status, body = self.request("/api/connect/qr?web")
            self.assertEqual(status, 200)
            self.assertIn(b"<svg", body)
            self.assertEqual(self.request("/api/connect/qr?wifi")[0], 404)
            with patch("server.is_loopback", return_value=False):
                self.assertEqual(self.request("/api/connect")[0], 403)
                self.assertEqual(self.request("/api/connect/qr?web")[0], 403)
        finally:
            self.server.connection = None

    def test_second_qr_arrival_requires_access_code(self):
        self.assertFalse(json.loads(self.request("/api/connect")[1])["phone_opened"])
        self.assertEqual(self.request("/api/connect/arrived", {"code": "WRONG123"})[0], 403)
        self.assertFalse(json.loads(self.request("/api/connect")[1])["phone_opened"])
        self.assertEqual(self.request("/api/connect/arrived", {"code": "abcd2345"})[0], 200)
        self.assertTrue(json.loads(self.request("/api/connect")[1])["phone_opened"])

    def test_upload_multiple_jpegs_and_make_pdf(self):
        sample = (Path(__file__).parent / "fixtures" / "sample.jpg").read_bytes()
        for index in range(2):
            status, body = self.upload(sample)
            self.assertEqual(status, 200)
            self.assertEqual(len(json.loads(body)["photos"]), index + 1)
        latest = json.loads(self.request("/api/latest")[1])
        folder = Path(self.uploads_dir.name) / latest["photo_folder"].split("/", 1)[1]
        self.assertTrue((folder / "001.jpg").is_file())
        self.assertTrue((folder / "002.jpg").is_file())
        self.assertFalse(latest["pdf_ready"])
        status, body = self.request("/api/photos/pdf", {})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["pdf_ready"])
        status, pdf = self.request("/api/photos/pdf")
        self.assertEqual(status, 200)
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertEqual(pdf.count(b"/Type /Page /Parent"), 2)
        self.assertEqual(pdf.count(sample), 2)
        self.assertTrue((folder / "photos.pdf").is_file())
        self.assertEqual(self.request("/api/photos/1"), (200, sample))
        status, _ = self.request("/api/photos/new", {})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(self.request("/api/latest")[1])["photos"], [])
        self.assertTrue((folder / "photos.pdf").is_file())

    def test_reject_bad_code_and_non_jpeg(self):
        sample = (Path(__file__).parent / "fixtures" / "sample.jpg").read_bytes()
        self.assertEqual(self.upload(sample, code="wrong")[0], 403)
        self.assertEqual(self.upload(b"not a jpeg")[0], 400)
        self.assertEqual(self.upload(sample, content_type="image/png")[0], 415)
        self.assertEqual(json.loads(self.request("/api/latest")[1])["photos"], [])

    def send_file(self, name, data, code="ABCD2345"):
        request = Request(self.base + "/api/files", data=data, headers={
            "Content-Type": "application/octet-stream", "X-File-Name": quote(name, safe=""),
            "X-Access-Code": code,
        })
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_common_formats_download_byte_for_byte_with_unicode_name(self):
        for extension, category in [("png", "image"), ("heic", "image"), ("mp3", "audio"), ("mp4", "video"),
                                    ("pdf", "pdf"), ("doc", "word"), ("docx", "word"), ("xlsx", "excel"),
                                    ("pptx", "slides"), ("zip", "archive"), ("custom", "file")]:
            with self.subTest(extension=extension):
                name = f"中文 文件.{extension}"
                data = bytes(range(256)) * 3
                status, result = self.send_file(name, data)
                self.assertEqual(status, 200)
                entry = json.loads(self.request("/api/latest")[1])["files"][-1]
                self.assertEqual(entry["category"], category)
                self.assertEqual(entry["bytes"], len(data))
                self.assertNotIn("path", entry)
                with urlopen(self.base + entry["download_url"]) as response:
                    self.assertEqual(response.read(), data)
                    self.assertIn("attachment;", response.headers["Content-Disposition"])
                    self.assertIn(quote(name, safe=""), response.headers["Content-Disposition"])

    def test_image_preview_and_pdf_from_generic_upload(self):
        sample = (Path(__file__).parent / "fixtures" / "sample.jpg").read_bytes()
        status, result = self.send_file("图片.jpg", sample)
        self.assertEqual(status, 200)
        self.assertTrue(result["pdf_included"])
        entry = json.loads(self.request("/api/latest")[1])["files"][0]
        with urlopen(self.base + entry["preview_url"]) as response:
            self.assertEqual(response.read(), sample)
            self.assertEqual(response.headers["Content-Type"], "image/jpeg")
            self.assertIn("inline", response.headers["Content-Disposition"])
        self.assertEqual(self.request("/api/photos/pdf", {})[0], 200)
        self.assertIn(sample, self.request("/api/photos/pdf")[1])
        stored = self.server.state.files.get(result["id"])["path"]
        self.request("/api/photos/new", {})
        self.assertEqual(json.loads(self.request("/api/latest")[1])["files"], [])
        self.assertTrue(stored.is_file())

    def test_file_auth_preview_safety_and_local_download_only(self):
        self.assertEqual(self.send_file("secret.txt", b"secret", code="wrong")[0], 403)
        self.assertFalse(self.server.state.files.status()["files"])
        for name in ("fake.jpg", "active.svg", "page.html"):
            status, result = self.send_file(name, b"<script>alert(1)</script>")
            self.assertEqual(status, 200)
            item = self.server.state.files.status()["files"][-1]
            self.assertIsNone(item["preview_url"])
            self.assertEqual(self.request(item["download_url"] + "/preview")[0], 404)
            with patch("server.is_loopback", return_value=False):
                self.assertEqual(self.request(item["download_url"])[0], 403)
        with patch("server.MAX_FILE_BYTES", 1):
            self.assertEqual(self.send_file("large.mp4", b"too big")[0], 413)

    def test_pdf_containers_export_api_and_access_control(self):
        sample = (Path(__file__).parent / 'fixtures' / 'sample.jpg').read_bytes()
        _, upload = self.send_file('photo.jpg', sample)
        status, body = self.request('/api/pdf-containers', {'action': 'create'})
        self.assertEqual(status, 200)
        key = json.loads(body)['pdf_containers'][0]['id']
        self.assertEqual(self.request('/api/pdf-containers', {'action': 'create'})[0], 400)
        self.assertEqual(self.request('/api/pdf-containers', {'action': 'add', 'id': key, 'file_ids': [upload['id']]})[0], 200)
        status, body = self.request('/api/exports', {'container_id': key})
        self.assertEqual(status, 200)
        job = json.loads(body)
        for _ in range(100):
            job = json.loads(self.request('/api/exports/' + job['id'])[1])
            if job['state'] != 'working':
                break
            time.sleep(.02)
        self.assertEqual(job['state'], 'ready', job)
        self.assertNotIn('path', job)
        status, data = self.request(job['download_url'])
        self.assertEqual(status, 200)
        self.assertTrue(data.startswith(b'%PDF-'))
        with patch('server.is_loopback', return_value=False):
            self.assertEqual(self.request('/api/pdf-containers', {'action': 'create'})[0], 403)
            self.assertEqual(self.request('/api/exports', {'all': True})[0], 403)
            self.assertEqual(self.request(job['download_url'])[0], 403)
        request = Request(self.base + '/api/pdf-containers', data=b'{"action":"create"}',
                          headers={'Content-Type': 'application/json', 'Origin': 'https://example.com'})
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        self.server.state.start_new_batch()
        self.assertEqual(self.request(job['download_url'])[0], 404)

    def test_image_thumbnail_endpoint_decodes_tiff_and_rejects_bad_image(self):
        from io import BytesIO
        from PIL import Image
        buffer = BytesIO()
        with Image.new('RGB', (40, 20), 'red') as photo:
            photo.save(buffer, 'TIFF')
        _, item = self.send_file('pages.tiff', buffer.getvalue())
        self.assertEqual(self.request('/api/files/' + item['id'] + '/thumbnail')[0], 200)
        status, image = self.request('/api/files/' + item['id'] + '/thumbnail')
        self.assertEqual(status, 200)
        self.assertTrue(image.startswith(b'\x89PNG\r\n\x1a\n'))
        with Image.open(BytesIO(image)) as thumb:
            self.assertEqual(thumb.size, (40, 20))
        _, item = self.send_file('bad.png', b'\x89PNG\r\n\x1a\ninvalid')
        self.assertEqual(self.request('/api/files/' + item['id'] + '/thumbnail')[0], 404)
        _, item = self.send_file('text.txt', b'hello')
        self.assertEqual(self.request('/api/files/' + item['id'] + '/thumbnail')[0], 404)


if __name__ == "__main__":
    unittest.main()
