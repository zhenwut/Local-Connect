import struct
import tempfile
import unittest
from pathlib import Path

from photo_pdf import inspect_jpeg, write_pdf


SAMPLE = (Path(__file__).parent / "fixtures" / "sample.jpg").read_bytes()


class PhotoPdfTests(unittest.TestCase):
    def test_jpeg_dimensions_and_exif_rotation(self):
        self.assertEqual(inspect_jpeg(SAMPLE), (4, 6, 1, "DeviceRGB"))
        tiff = (
            b"II" + struct.pack("<HIH", 42, 8, 1) +
            struct.pack("<HHI", 0x0112, 3, 1) +
            struct.pack("<H", 6) + b"\0\0" + struct.pack("<I", 0)
        )
        exif = b"Exif\0\0" + tiff
        rotated = SAMPLE[:2] + b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif + SAMPLE[2:]
        self.assertEqual(inspect_jpeg(rotated), (4, 6, 6, "DeviceRGB"))

    def test_pdf_uses_landscape_page_for_rotated_photo(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "photos.pdf"
            write_pdf([{
                "path": Path(__file__).parent / "fixtures" / "sample.jpg",
                "width": 4, "height": 6, "orientation": 6, "colorspace": "DeviceRGB",
            }], destination)
            data = destination.read_bytes()
        self.assertIn(b"/MediaBox [0 0 841.89 595.28]", data)
        self.assertIn(b"/Filter /DCTDecode", data)
        self.assertIn(b"startxref", data)

    def test_reject_non_jpeg(self):
        with self.assertRaises(ValueError):
            inspect_jpeg(b"\x89PNG\r\n")


if __name__ == "__main__":
    unittest.main()
