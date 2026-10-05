import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

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


if __name__ == "__main__":
    unittest.main()
