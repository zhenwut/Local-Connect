"""Local conversion engines. Uploaded source files are never modified."""
import os
import io
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from html import escape
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '.deps'))
IMAGE_FORMATS = {'jpg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'avif'}
OFFICE_FORMATS = {'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'}
FORMATS = IMAGE_FORMATS | OFFICE_FORMATS | {'html', 'pdf'}
ALIASES = {'jpeg': 'jpg', 'jfif': 'jpg', 'tif': 'tiff', 'htm': 'html'}
MAX_CONVERT_BYTES = 500 * 1024 ** 2
MAX_PAGES = 500


def file_format(name):
    ext = Path(name).suffix.lower().lstrip('.')
    return ALIASES.get(ext, ext)


def thumbnail_png(source):
    """Decode one bounded image frame for the receiver's PDF tile."""
    from PIL import Image, ImageOps
    try:
        with Image.open(source) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError('图片尺寸过大')
            oriented = ImageOps.exif_transpose(image)
            try:
                oriented.thumbnail((320, 320))
                output = io.BytesIO()
                oriented.save(output, format='PNG')
                return output.getvalue()
            finally:
                oriented.close()
    except Image.DecompressionBombError as error:
        raise ValueError('图片尺寸过大') from error


def browser_path():
    for base in (os.environ.get('PROGRAMFILES', ''), os.environ.get('PROGRAMFILES(X86)', ''), os.environ.get('LOCALAPPDATA', '')):
        for relative in ('Google/Chrome/Application/chrome.exe', 'Microsoft/Edge/Application/msedge.exe'):
            path = Path(base) / relative
            if path.is_file():
                return str(path)
    return shutil.which('google-chrome') or shutil.which('chromium')


def capabilities():
    try:
        from PIL import Image
        from pypdf import PdfWriter
    except ImportError:
        return {'formats': [], 'hint': '请先运行 python -m pip install --target .deps -r requirements.txt'}
    formats = IMAGE_FORMATS | {'pdf'}
    if os.name == 'nt':
        # Conversion errors still report missing/unconfigured Office installations.
        formats |= OFFICE_FORMATS
    if browser_path():
        formats |= {'html'}
    return {'formats': sorted(formats), 'hint': '图片、PDF、DOC/DOCX、XLS/XLSX、PPT/PPTX、HTML；Office 格式需要本机安装对应应用。'}


def run_hidden(args, timeout=120, cancel=None):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        deadline = time.monotonic() + timeout
        while True:
            if (cancel and cancel.is_set()) or time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(args, timeout)
            try:
                output, error = process.communicate(timeout=min(1, deadline - time.monotonic()))
                break
            except subprocess.TimeoutExpired:
                continue
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        else:
            process.kill()
        process.communicate()
        raise ValueError('服务已关闭，转换已取消' if cancel and cancel.is_set() else '转换超时；请检查文件能否正常打开，或将大文件拆分后再试')
    if process.returncode:
        detail = (error or output).decode('utf-8', 'replace').strip()[-600:]
        raise ValueError('转换失败：' + detail)


class StaticHTML(HTMLParser):
    """Only printable static HTML; no scripts, navigation, external/local resources."""
    tags = set('html head body title style div span p br hr h1 h2 h3 h4 h5 h6 b strong i em u s small sub sup pre code blockquote ul ol li dl dt dd table thead tbody tfoot tr th td caption colgroup col img section article header footer main figure figcaption a'.split())
    attrs = {'style', 'class', 'id', 'colspan', 'rowspan', 'width', 'height', 'alt', 'dir', 'lang'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'iframe', 'object', 'svg', 'math'):
            self.skipping += 1
        if self.skipping or tag not in self.tags:
            return
        allowed = []
        for key, value in attrs:
            value = value or ''
            if key in self.attrs or (tag == 'img' and key == 'src' and value.lower().startswith(('data:image/png;', 'data:image/jpeg;', 'data:image/webp;', 'data:image/gif;'))):
                allowed.append(f' {key}="{escape(value, quote=True)}"')
        self.parts.append('<' + tag + ''.join(allowed) + '>')

    def handle_endtag(self, tag):
        if tag in ('script', 'iframe', 'object', 'svg', 'math') and self.skipping:
            self.skipping -= 1
            return
        if not self.skipping and tag in self.tags:
            self.parts.append('</' + tag + '>')

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(escape(data))


def html_pdf(source, destination, work, cancel=None):
    browser = browser_path()
    if not browser:
        raise ValueError('HTML 转换需要电脑安装 Chrome 或 Edge')
    data = source.read_bytes()
    if len(data) > 20 * 1024 ** 2:
        raise ValueError('HTML 转换单个文件不能超过 20 MiB')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('gb18030', 'replace')
    parser = StaticHTML()
    parser.feed(text)
    content = ('<!doctype html><meta charset="utf-8">' + ''.join(parser.parts)).encode('utf-8')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Content-Security-Policy', "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        run_hidden([browser, '--headless=new', '--no-first-run', '--disable-extensions', '--disable-background-networking',
                    '--no-pdf-header-footer', '--no-default-browser-check', '--timeout=15000',
                    '--user-data-dir=' + str(work / 'browser'), '--print-to-pdf=' + str(destination),
                    f'http://127.0.0.1:{server.server_port}/'], timeout=45, cancel=cancel)
    finally:
        server.shutdown()
        server.server_close()


def office_pdf(source, destination, work, cancel=None):
    if os.name != 'nt':
        raise ValueError('Office 转换需要 Windows 和 Microsoft Office')
    owned = work / 'office-process.json'
    try:
        run_hidden(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                    '-File', str(ROOT / 'office_pdf.ps1'), '-InputPath', str(source),
                    '-OutputPath', str(destination), '-ProcessRecord', str(owned)], cancel=cancel)
    finally:
        # Stop only the conversion-owned process, checked against its creation time.
        if owned.is_file():
            run_hidden(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                        '-File', str(ROOT / 'office_pdf.ps1'), '-ProcessRecord', str(owned), '-Cleanup'], timeout=20)


def convert(files, destination, cancel=None, rotations=None):
    from PIL import Image, ImageOps
    from pypdf import PdfReader, PdfWriter
    if not files or len({file_format(f['name']) for f in files}) != 1:
        raise ValueError('一个 PDF 容器只能放入相同格式的文件')
    kind = file_format(files[0]['name'])
    if kind not in FORMATS:
        raise ValueError('此格式暂不支持转为 PDF，可直接下载原文件')
    if sum(f['bytes'] for f in files) > MAX_CONVERT_BYTES:
        raise ValueError('每个 PDF 容器最多转换 500 MiB 文件')
    rotations = rotations or {}
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='convert-', dir=destination.parent) as folder:
        work = Path(folder)
        writer = PdfWriter()
        try:
            for index, item in enumerate(files):
                if cancel and cancel.is_set():
                    raise ValueError('服务已关闭，转换已取消')
                source = Path(item['path']).resolve()
                output = work / f'{index}.pdf'
                try:
                    if kind in IMAGE_FORMATS:
                        with Image.open(source) as image:
                            # TIFF pages are documents; animated images use their first frame.
                            frames = getattr(image, 'n_frames', 1) if kind == 'tiff' else 1
                            if frames + len(writer.pages) > MAX_PAGES:
                                raise ValueError('每个容器最多 500 页')
                            for frame in range(frames):
                                if cancel and cancel.is_set():
                                    raise ValueError('服务已关闭，转换已取消')
                                image.seek(frame)
                                if image.width * image.height > 40_000_000:
                                    raise ValueError('单张图片不能超过 4000 万像素')
                                oriented = ImageOps.exif_transpose(image)
                                angle = rotations.get(item['id'], 0)
                                rotated = oriented.transpose({90: Image.Transpose.ROTATE_270,
                                                              180: Image.Transpose.ROTATE_180,
                                                              270: Image.Transpose.ROTATE_90}[angle]) if angle else oriented
                                rgba = rotated.convert('RGBA')
                                rgb = Image.new('RGB', rgba.size, 'white')
                                rgb.paste(rgba, mask=rgba.getchannel('A'))
                                rgb.save(output, 'PDF', resolution=150, quality=95, subsampling=0)
                                rgb.close()
                                rgba.close()
                                if rotated is not oriented:
                                    rotated.close()
                                oriented.close()
                                writer.append(str(output))
                    else:
                        if kind in OFFICE_FORMATS:
                            office_pdf(source, output, work, cancel)
                        elif kind == 'html':
                            html_pdf(source, output, work, cancel)
                        else:
                            output = source
                        reader = PdfReader(output)
                        if reader.is_encrypted:
                            raise ValueError('请先移除 PDF 密码后再转换')
                        if len(reader.pages) + len(writer.pages) > MAX_PAGES:
                            raise ValueError('每个容器最多 500 页')
                        writer.append(reader)
                except Exception as error:
                    raise ValueError(f'{item["name"]}：{error}') from error
            if not writer.pages:
                raise ValueError('文件没有可导出的页面')
            writer.write(str(destination))
        finally:
            writer.close()
