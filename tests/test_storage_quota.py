import io
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from file_transfer import FileStore
from pdf_workspace import PdfWorkspace
from photo_pdf import inspect_jpeg
from server import TransferState
from storage_quota import StorageQuota


class StorageQuotaTests(unittest.TestCase):
    def test_old_transfers_count_across_batches_without_changing_existing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = root / 'files-0123456789abcdef' / 'old.txt'
            old.parent.mkdir()
            old.write_bytes(b'preserve')
            unrelated = root / 'private.txt'
            unrelated.write_bytes(b'x' * 100)
            quota = StorageQuota(root, limit_bytes=12, min_free_bytes=0)
            store = FileStore(root, quota=quota)
            store.receive(io.BytesIO(b'1234'), 4, 'new.txt')
            store.new_batch()
            with self.assertRaisesRegex(ValueError, '全局空间上限'):
                store.receive(io.BytesIO(b'12'), 2, 'too-much.txt')
            self.assertEqual(old.read_bytes(), b'preserve')
            self.assertEqual(unrelated.read_bytes(), b'x' * 100)
            self.assertEqual(quota.reserved, 0)

    def test_parallel_reservations_and_failed_upload_release_capacity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            quota = StorageQuota(root, limit_bytes=5, min_free_bytes=0)
            first = quota.reserve(4)
            with self.assertRaisesRegex(ValueError, '全局空间上限'):
                quota.reserve(2)
            quota.release(first)
            store = FileStore(root, quota=quota)
            with self.assertRaisesRegex(ValueError, '不完整'):
                store.receive(io.BytesIO(b'x'), 5, 'broken.bin')
            self.assertEqual(quota.reserved, 0)
            item = store.receive(io.BytesIO(b'hello'), 5, 'good.bin')
            self.assertEqual(item['path'].read_bytes(), b'hello')

    def test_export_over_limit_keeps_uploaded_original(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            quota = StorageQuota(root, limit_bytes=6, min_free_bytes=0)
            store = FileStore(root, quota=quota)
            item = store.receive(io.BytesIO(b'hello'), 5, 'good.bin')
            workspace = PdfWorkspace(store)
            try:
                job = workspace.start_export({'all': True})
                for _ in range(100):
                    status = workspace.get_job(job['id'])
                    if status['state'] != 'working':
                        break
                    time.sleep(.01)
                self.assertEqual(status['state'], 'error')
                self.assertIn('全局空间上限', status['message'])
                self.assertEqual(item['path'].read_bytes(), b'hello')
                self.assertFalse(list(root.rglob('*.zip')))
                self.assertEqual(quota.reserved, 0)
            finally:
                workspace.close()

    def test_rebuilding_photo_pdf_credits_the_file_it_replaces(self):
        sample = (Path(__file__).parent / 'fixtures' / 'sample.jpg').read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            state = TransferState('ABCD2345', folder)
            state.quota.min_free_bytes = 0
            try:
                metadata = inspect_jpeg(sample)
                state.add_photo(sample, metadata)
                state.make_pdf()
                old_pdf = state.pdf_path()
                old_size = old_pdf.stat().st_size
                state.add_photo(sample, metadata)
                expected_new = 2 * len(sample) + 1024 * 1024
                state.quota.limit_bytes = 2 * len(sample) + expected_new
                state.make_pdf()
                self.assertGreater(state.pdf_path().stat().st_size, old_size)
                self.assertFalse(list(Path(folder).rglob('*.part')))
            finally:
                state.pdf_workspace.close()

    def test_windows_reparse_attribute_catches_junction_without_path_is_junction(self):
        path = Mock()
        path.is_symlink.return_value = False
        path.lstat.return_value = SimpleNamespace(st_file_attributes=0x400)
        with patch('storage_quota.os.name', 'nt'):
            self.assertTrue(StorageQuota._is_link(path))
        path.lstat.return_value = SimpleNamespace(st_file_attributes=0)
        with patch('storage_quota.os.name', 'nt'):
            self.assertFalse(StorageQuota._is_link(path))


if __name__ == '__main__':
    unittest.main()
