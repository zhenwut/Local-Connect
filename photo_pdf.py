"""Validate JPEGs and place them on A4 PDF pages without extra packages."""

import os
import struct
from pathlib import Path


A4_WIDTH = 595.28
A4_HEIGHT = 841.89
MARGIN = 24
SOF_MARKERS = {0xC0, 0xC1, 0xC2}
TRANSFORMS = {
    1: (1, 0, 0, 1, 0, 0),
    2: (-1, 0, 0, 1, 1, 0),
    3: (-1, 0, 0, -1, 1, 1),
    4: (1, 0, 0, -1, 0, 1),
    5: (0, 1, 1, 0, 0, 0),
    6: (0, -1, 1, 0, 0, 1),
    7: (0, -1, -1, 0, 1, 1),
    8: (0, 1, -1, 0, 1, 0),
}


def _exif_orientation(segment):
    if not segment.startswith(b"Exif\x00\x00"):
        return 1
    tiff = segment[6:]
    if len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
        return 1
    endian = "<" if tiff[:2] == b"II" else ">"
    try:
        if struct.unpack_from(endian + "H", tiff, 2)[0] != 42:
            return 1
        ifd = struct.unpack_from(endian + "I", tiff, 4)[0]
        count = struct.unpack_from(endian + "H", tiff, ifd)[0]
        for index in range(min(count, 256)):
            offset = ifd + 2 + index * 12
            tag, kind, amount = struct.unpack_from(endian + "HHI", tiff, offset)
            if tag == 0x0112 and kind == 3 and amount == 1:
                orientation = struct.unpack_from(endian + "H", tiff, offset + 8)[0]
                return orientation if orientation in TRANSFORMS else 1
    except struct.error:
        return 1
    return 1


def inspect_jpeg(data):
    """Return (width, height, orientation, colorspace) or reject invalid input."""
    if len(data) < 8 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ValueError("不是完整的 JPG 照片")
    offset = 2
    width = height = components = None
    orientation = 1
    saw_scan = False
    while offset + 3 < len(data):
        if data[offset] != 0xFF:
            raise ValueError("JPG 文件结构有误")
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker == 0xDA:
            saw_scan = True
            break
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            break
        length = struct.unpack_from(">H", data, offset)[0]
        if length < 2 or offset + length > len(data):
            raise ValueError("JPG 文件结构有误")
        segment = data[offset + 2:offset + length]
        if marker == 0xE1:
            orientation = _exif_orientation(segment)
        if marker in SOF_MARKERS:
            if len(segment) < 6:
                raise ValueError("JPG 尺寸信息有误")
            height, width, components = struct.unpack_from(">HHB", segment, 1)
        offset += length
    if not saw_scan or not width or not height or components not in (1, 3):
        raise ValueError("只支持灰度或 RGB 的普通 JPG 照片")
    if width > 30000 or height > 30000:
        raise ValueError("照片尺寸过大")
    colorspace = "DeviceGray" if components == 1 else "DeviceRGB"
    return width, height, orientation, colorspace


def _page_layout(width, height, orientation):
    if orientation >= 5:
        width, height = height, width
    page_width, page_height = (A4_HEIGHT, A4_WIDTH) if width > height else (A4_WIDTH, A4_HEIGHT)
    scale = min((page_width - 2 * MARGIN) / width, (page_height - 2 * MARGIN) / height)
    draw_width, draw_height = width * scale, height * scale
    x, y = (page_width - draw_width) / 2, (page_height - draw_height) / 2
    a, b, c, d, e, f = TRANSFORMS[orientation]
    matrix = (
        a * draw_width, b * draw_height, c * draw_width, d * draw_height,
        x + e * draw_width, y + f * draw_height,
    )
    return page_width, page_height, matrix


def write_pdf(photos, destination):
    """Write a PDF with one original JPEG per page. photos is a list of dicts."""
    if not photos:
        raise ValueError("没有可转换的照片")
    destination = Path(destination)
    offsets = [0] * (3 + 3 * len(photos))
    total_objects = len(offsets) - 1
    with destination.open("wb") as output:
        output.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

        def obj(number, content):
            offsets[number] = output.tell()
            output.write(f"{number} 0 obj\n".encode("ascii"))
            output.write(content)
            output.write(b"\nendobj\n")

        obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
        kids = " ".join(f"{3 + 3 * index} 0 R" for index in range(len(photos)))
        obj(2, f"<< /Type /Pages /Count {len(photos)} /Kids [{kids}] >>".encode("ascii"))
        for index, photo in enumerate(photos):
            page_no = 3 + 3 * index
            image_no = page_no + 1
            content_no = page_no + 2
            page_width, page_height, matrix = _page_layout(
                photo["width"], photo["height"], photo["orientation"]
            )
            obj(page_no, (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width:.2f} {page_height:.2f}] "
                f"/Resources << /XObject << /Im{index} {image_no} 0 R >> >> "
                f"/Contents {content_no} 0 R >>"
            ).encode("ascii"))
            image_path = Path(photo["path"])
            image_size = image_path.stat().st_size
            offsets[image_no] = output.tell()
            output.write(f"{image_no} 0 obj\n".encode("ascii"))
            output.write((
                f"<< /Type /XObject /Subtype /Image /Width {photo['width']} "
                f"/Height {photo['height']} /ColorSpace /{photo['colorspace']} "
                f"/BitsPerComponent 8 /Filter /DCTDecode /Length {image_size} >>\nstream\n"
            ).encode("ascii"))
            with image_path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
            output.write(b"\nendstream\nendobj\n")
            content = (
                "q\n" + " ".join(f"{value:.4f}" for value in matrix) +
                f" cm\n/Im{index} Do\nQ\n"
            ).encode("ascii")
            obj(content_no, (
                f"<< /Length {len(content)} >>\nstream\n".encode("ascii") +
                content + b"endstream"
            ))
        startxref = output.tell()
        output.write(f"xref\n0 {total_objects + 1}\n".encode("ascii"))
        output.write(b"0000000000 65535 f \n")
        for number in range(1, total_objects + 1):
            output.write(f"{offsets[number]:010d} 00000 n \n".encode("ascii"))
        output.write((
            f"trailer\n<< /Size {total_objects + 1} /Root 1 0 R >>\n"
            f"startxref\n{startxref}\n%%EOF\n"
        ).encode("ascii"))
        output.flush()
        os.fsync(output.fileno())
