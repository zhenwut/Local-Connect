import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from file_transfer import CHUNK_BYTES, FileStore, safe_name


class FileStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = FileStore(self.directory.name)

    def test_streaming_duplicate_names_and_empty_files(self):
        class BoundedReader(io.BytesIO):
            def read(self, size=-1):
                if not 0 < size <= CHUNK_BYTES:
                    raise AssertionError("Unbounded file read")
                return super().read(size)
        data = b"video-data" * (CHUNK_BYTES // 3)
        first = self.store.receive(BoundedReader(data), len(data), "旅行.mp4")
        second = self.store.receive(io.BytesIO(b"other"), 5, "旅行.mp4")
        empty = self.store.receive(io.BytesIO(), 0, "empty.txt")
        self.assertEqual(first["path"].read_bytes(), data)
        self.assertEqual(second["path"].read_bytes(), b"other")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(empty["path"].stat().st_size, 0)

    def test_incomplete_upload_is_removed_and_quota_released(self):
        with self.assertRaisesRegex(ValueError, "不完整"):
            self.store.receive(io.BytesIO(b"short"), 50, "broken.zip")
        self.assertEqual(self.store.status()["files"], [])
        self.assertEqual(self.store.pending, {})
        self.assertEqual(list(Path(self.directory.name).rglob("*.part")), [])

    def test_new_batch_during_upload_does_not_publish_partial_file(self):
        store = self.store
        class SwitchingReader(io.BytesIO):
            def read(self, size=-1):
                store.new_batch()
                return super().read(size)
        with self.assertRaisesRegex(ValueError, "新批次"):
            store.receive(SwitchingReader(b"data"), 4, "record.wav")
        self.assertEqual(store.status()["files"], [])
        self.assertFalse(list(Path(self.directory.name).rglob("*.part")))

    def test_quotas_and_safe_windows_paths(self):
        for name in ("../../文件.docx", "C:\\secret\\文件.docx", "CON", "abc:secret", "..", "😀" * 200 + ".xlsx"):
            with self.subTest(name=name):
                item = self.store.receive(io.BytesIO(b"x"), 1, name)
                item["path"].resolve().relative_to(Path(self.directory.name).resolve())
                self.assertEqual(item["path"].read_bytes(), b"x")
                self.assertLessEqual(len(item["name"].encode("utf-8")), 180)
        self.assertEqual(safe_name("../文件.docx"), "文件.docx")
        with patch("file_transfer.MAX_FILES", 1):
            with self.assertRaisesRegex(ValueError, "100"):
                self.store.receive(io.BytesIO(b"x"), 1, "excess.pdf")
        with patch("file_transfer.MAX_FILES_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "10 GiB"):
                self.store.receive(io.BytesIO(b"x"), 1, "excess.pdf")
