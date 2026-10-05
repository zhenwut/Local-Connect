"""Isolated fixture server for browser_smoke.cjs; never enables the hotspot."""
import json
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import TransferServer

with tempfile.TemporaryDirectory(prefix="local-connect-browser-") as folder:
    root = Path(folder)
    sample = (Path(__file__).parent / "fixtures" / "sample.jpg").read_bytes()
    names = {
        "照片.jpg": sample,
        "项目说明.docx": b"sample-word-data",
        "年度报表.xlsx": b"sample-excel-data",
        "音乐.mp3": b"sample-audio-data",
        "旅行视频.mp4": b"sample-video-data",
        "说明书.pdf": b"%PDF-1.4\nsample",
        "原片.heic": b"unsupported-preview-but-downloadable",
        "预览损坏.png": b"\x89PNG\r\n\x1a\ninvalid",
    }
    for name, data in names.items():
        (root / name).write_bytes(data)
    server = TransferServer(("127.0.0.1", 0), "ABCD2345", root / "uploads")
    class SimulatedConnection:
        def snapshot(self):
            url = f"http://127.0.0.1:{server.server_port}/"
            return {"mode": "web", "ssid": "浏览器测试", "password": "test-password",
                    "web_url": url, "web_qr": url + "#code=ABCD2345", "code": "ABCD2345"}
    server.connection = SimulatedConnection()
    def run_server():
        try:
            server.serve_forever()
        finally:
            server.server_close()
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    server.receiver_lifecycle.start()
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}",
                      "files": [str(root / name) for name in names]}), flush=True)
    try:
        sys.stdin.readline()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
