"""Space budget for files created by Local Connect inside its uploads folder."""

import os
import re
import shutil
import stat
import threading
from pathlib import Path


DEFAULT_LIMIT_BYTES = 20 * 1024 ** 3
MIN_FREE_BYTES = 512 * 1024 ** 2
PHOTO_BATCH = re.compile(r"^\d{8}-\d{6}-[a-f0-9]{6}$")
FILE_BATCH = re.compile(r'^files-[a-f0-9]{16}$')
EXPORT_BATCH = re.compile(r'^exports-[a-f0-9]{24}$')


class StorageQuota:
    def __init__(self, root, limit_bytes=DEFAULT_LIMIT_BYTES, min_free_bytes=MIN_FREE_BYTES):
        self.root = Path(root)
        self.limit_bytes = limit_bytes
        self.min_free_bytes = min_free_bytes
        self.lock = threading.Lock()
        self.reserved = 0

    def _managed_folders(self):
        if not self.root.is_dir():
            return
        for folder in self.root.iterdir():
            name = folder.name
            if (folder.is_dir() and not self._is_link(folder) and
                    (FILE_BATCH.fullmatch(name) or EXPORT_BATCH.fullmatch(name)
                     or name == '.thumbnails' or PHOTO_BATCH.fullmatch(name))):
                yield folder

    @staticmethod
    def _is_link(path):
        try:
            if path.is_symlink():
                return True
            if os.name == 'nt':
                # Available on Windows in Python 3.10, before Path.is_junction().
                return bool(getattr(path.lstat(), 'st_file_attributes', 0)
                            & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))
        except OSError:
            return True  # Do not traverse a directory whose attributes cannot be checked.
        return False

    def _used_bytes(self):
        total = 0
        for folder in self._managed_folders():
            for parent, directories, files in os.walk(folder, followlinks=False):
                directories[:] = [name for name in directories if not self._is_link(Path(parent) / name)]
                for name in files:
                    path = Path(parent) / name
                    if not self._is_link(path):
                        try:
                            total += path.stat().st_size
                        except FileNotFoundError:
                            pass
        return total

    def _free_bytes(self):
        place = self.root if self.root.exists() else self.root.parent
        return shutil.disk_usage(place).free

    def reserve(self, expected_bytes, replace_bytes=0):
        """Reserve room before writing. The caller must always release the ticket."""
        if expected_bytes < 0 or replace_bytes < 0:
            raise ValueError('文件大小无效')
        with self.lock:
            if self._used_bytes() + self.reserved + expected_bytes - replace_bytes > self.limit_bytes:
                raise ValueError('Local Connect 文件已达到全局空间上限；请自行整理 uploads 后重试')
            if self._free_bytes() - self.reserved - expected_bytes < self.min_free_bytes:
                raise ValueError('电脑剩余空间不足；请释放磁盘空间后重试')
            self.reserved += expected_bytes
        return expected_bytes

    def check(self, ticket, replace_bytes=0):
        """Check the actual output before publishing it. Never remove existing files."""
        with self.lock:
            remaining = self.reserved - ticket
            if self._used_bytes() + remaining - replace_bytes > self.limit_bytes:
                raise ValueError('生成的文件超过 Local Connect 全局空间上限')
            if self._free_bytes() - remaining < self.min_free_bytes:
                raise ValueError('电脑剩余空间不足，无法保存生成的文件')

    def release(self, ticket):
        with self.lock:
            self.reserved -= ticket
