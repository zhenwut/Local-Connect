"""Bounded-memory file storage, independent of browser-supplied MIME types."""

import os
import re
import secrets
import threading
from pathlib import Path

MAX_FILE_BYTES = 2 * 1024 ** 3
MAX_FILES = 100
MAX_FILES_BYTES = 10 * 1024 ** 3
CHUNK_BYTES = 1024 * 1024


def safe_name(name):
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", name).strip(" .")
    if not name:
        name = "未命名文件"
    if name.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    suffix = Path(name).suffix.encode("utf-8")[:30].decode("utf-8", "ignore")
    if len(name.encode("utf-8")) > 180:
        name = Path(name).stem.encode("utf-8")[:180 - len(suffix.encode("utf-8"))].decode("utf-8", "ignore") + suffix
    return name


def category(name):
    extension = Path(name).suffix.lower().lstrip(".")
    groups = {
        "image": "jpg jpeg jfif png gif webp avif bmp ico svg heic heif tif tiff raw dng psd",
        "audio": "mp3 wav aac m4a flac ogg opus wma aiff amr",
        "video": "mp4 mov mkv avi webm m4v mpeg mpg 3gp ts wmv flv",
        "pdf": "pdf", "word": "doc docx odt rtf", "excel": "xls xlsx xlsm ods",
        "csv": "csv tsv", "ebook": "epub mobi azw azw3 fb2",
        "slides": "ppt pptx odp", "archive": "zip rar 7z gz tar tgz bz2 xz zst",
        "text": "txt md log json xml yaml yml html css js py ini cfg toml rst srt vtt",
    }
    return next((key for key, extensions in groups.items() if extension in extensions.split()), "file")


def image_type(header):
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if header.startswith(b"BM"):
        return "image/bmp"
    if header[4:8] == b"ftyp" and header[8:12] in (b"avif", b"avis"):
        return "image/avif"
    return None


class FileStore:
    def __init__(self, root, quota=None):
        self.root = Path(root)
        self.quota = quota
        self.lock = threading.Lock()
        self.batch = "files-" + secrets.token_hex(8)
        self.files = {}
        self.pending = {}
        self.version = 0

    def status(self):
        with self.lock:
            return {"files_version": self.version,
                    "files": [{k: v for k, v in item.items() if k not in ("path", "preview_type")} for item in self.files.values()],
                    "files_folder": f"uploads/{self.batch}" if self.files else ""}

    def new_batch(self):
        with self.lock:
            self.batch = "files-" + secrets.token_hex(8)
            self.files = {}
            self.version += 1

    def get(self, file_id):
        with self.lock:
            item = self.files.get(file_id)
            return item.copy() if item else None

    def receive(self, stream, length, name):
        if length < 0 or length > MAX_FILE_BYTES:
            raise ValueError("单个文件不能超过 2 GiB")
        name = safe_name(name)
        file_id = secrets.token_hex(16)
        ticket = None
        with self.lock:
            batch = self.batch
            pending = [size for owner, size in self.pending.values() if owner == batch]
            if len(self.files) + len(pending) >= MAX_FILES:
                raise ValueError("每次最多 100 个文件，请重新打开电脑接收页后继续")
            if sum(item["bytes"] for item in self.files.values()) + sum(pending) + length > MAX_FILES_BYTES:
                raise ValueError("每批文件总量不能超过 10 GiB")
            if self.quota:
                ticket = self.quota.reserve(length)
            self.pending[file_id] = (batch, length)
        folder = self.root / batch / file_id
        path = folder / name
        temporary = folder / "upload.part"
        committed = False
        try:
            folder.mkdir(parents=True, exist_ok=False)
            remaining = length
            header = b""
            with temporary.open("xb") as destination:
                while remaining:
                    chunk = stream.read(min(remaining, CHUNK_BYTES))
                    if not chunk:
                        raise ValueError("文件传输不完整，请重新上传")
                    if not header:
                        header = chunk[:32]
                    destination.write(chunk)
                    remaining -= len(chunk)
            preview_type = image_type(header)
            item = {"id": file_id, "name": name, "bytes": length, "path": path,
                    "category": "image" if preview_type else category(name),
                    "preview_type": preview_type,
                    "download_url": f"/api/files/{file_id}",
                    "preview_url": f"/api/files/{file_id}/preview" if preview_type else None}
            with self.lock:
                if batch != self.batch:
                    raise ValueError("电脑已开始新批次，请重新上传此文件")
                if self.quota:
                    self.quota.check(ticket)
                os.replace(temporary, path)
                self.files[file_id] = item
                self.version += 1
                committed = True
            return item.copy()
        finally:
            try:
                with self.lock:
                    self.pending.pop(file_id, None)
                if not committed:
                    temporary.unlink(missing_ok=True)
                    if folder.exists():
                        folder.rmdir()
            finally:
                if self.quota:
                    self.quota.release(ticket)
