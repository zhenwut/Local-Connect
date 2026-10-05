import io
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from file_transfer import FileStore
from pdf_convert import convert
from pdf_workspace import PdfWorkspace
from PIL import Image
from pypdf import PdfReader, PdfWriter


class PdfWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.files = FileStore(self.root)
        self.workspace = PdfWorkspace(self.files)

    def tearDown(self):
        self.temp.cleanup()

    def upload(self, name, data=b'hello'):
        return self.files.receive(io.BytesIO(data), len(data), name)

    def image(self, name='photo.jpg', kind='JPEG'):
        buffer = io.BytesIO()
        with Image.new('RGB', (48, 32), 'red') as image:
            image.save(buffer, kind)
        return self.upload(name, buffer.getvalue())

    def create(self):
        return self.workspace.action({'action': 'create'})['pdf_containers'][-1]['id']

    def add(self, key, *files):
        return self.workspace.action({'action': 'add', 'id': key, 'file_ids': [f['id'] for f in files]})

    def wait_job(self, payload):
        job = self.workspace.start_export(payload)
        for _ in range(200):
            job = self.workspace.get_job(job['id'], True)
            if job['state'] != 'working':
                return job
            time.sleep(.025)
        self.fail('export timed out')

    def test_same_format_atomic_move_remove_and_naming(self):
        a, b, c = self.image(), self.image('second.jpeg'), self.image('third.png', 'PNG')
        first = self.create()
        with self.assertRaises(ValueError):
            self.create()
        self.add(first, a, b)
        second = self.create()
        with self.assertRaises(ValueError):
            self.add(second, b, c)
        self.assertEqual(len(self.workspace.containers[first]['file_ids']), 2)
        self.add(second, b)
        self.assertEqual(self.workspace.containers[first]['file_ids'], [a['id']])
        with self.assertRaises(ValueError):
            self.add(second, c)
        self.workspace.action({'action': 'rename', 'id': second, 'name': '../相册.pdf'})
        self.assertEqual(self.workspace.containers[second]['name'], '相册')
        self.workspace.action({'action': 'delete', 'id': second})
        self.assertIsNotNone(self.files.get(b['id']))
        self.workspace.action({'action': 'remove', 'id': first, 'file_id': a['id']})
        self.add(first, c)  # Empty containers can accept another format.
        self.assertEqual(self.workspace.containers[first]['format'], 'png')

    def test_pdf_export_and_zip_replace_grouped_files_preserve_duplicates(self):
        a, b = self.image(), self.image('other.jpeg')
        self.upload('same.txt', b'first')
        self.upload('same.txt', b'second')
        key = self.create()
        self.add(key, a, b)
        job = self.wait_job({'container_id': key})
        self.assertEqual(job['state'], 'ready', job)
        self.assertEqual(len(PdfReader(job['path']).pages), 2)
        job = self.wait_job({'all': True})
        self.assertEqual(job['state'], 'ready', job)
        with zipfile.ZipFile(job['path']) as archive:
            self.assertEqual(set(archive.namelist()), {'pdf1.pdf', 'same.txt', 'same (2).txt'})
            self.assertEqual(archive.read('same.txt'), b'first')
            self.assertEqual(archive.read('same (2).txt'), b'second')
            self.assertEqual(len(PdfReader(io.BytesIO(archive.read('pdf1.pdf'))).pages), 2)
        self.assertEqual(job['bytes'], job['path'].stat().st_size)
        self.workspace.reset()
        self.assertIsNone(self.workspace.get_job(job['id']))
        self.assertEqual(self.workspace.status()['pdf_containers'], [])

    def test_deleted_numbers_are_reused_without_renaming_survivors(self):
        first = self.create()
        self.workspace.action({'action': 'delete', 'id': first})
        first = self.create()
        self.assertEqual(self.workspace.containers[first]['name'], 'pdf1')
        self.add(first, self.image())
        second = self.create()
        self.add(second, self.image('second.jpg'))
        self.workspace.action({'action': 'delete', 'id': first})
        replacement = self.create()
        self.assertEqual(self.workspace.containers[replacement]['name'], 'pdf1')
        self.assertEqual(self.workspace.containers[second]['name'], 'pdf2')
        self.workspace.action({'action': 'rename', 'id': replacement, 'name': 'PDF3'})
        self.add(replacement, self.image('third.jpg'))
        # Renaming reserves its original number and avoids colliding with names.
        self.assertEqual(self.workspace.containers[self.create()]['name'], 'pdf4')

    def test_selected_zip_only_includes_chosen_files_and_containers(self):
        first = self.upload('chosen.txt', b'chosen')
        second = self.upload('skip.txt', b'skip')
        photo = self.image()
        key = self.create()
        self.add(key, photo)
        bad_key = self.create()
        self.add(bad_key, self.upload('bad.docx', b'broken'))
        job = self.wait_job({'selected': {'file_ids': [first['id']], 'container_ids': []}})
        self.assertEqual(job['state'], 'ready', job)
        with zipfile.ZipFile(job['path']) as archive:
            self.assertEqual(archive.namelist(), ['chosen.txt'])
            self.assertEqual(archive.read('chosen.txt'), b'chosen')
        job = self.wait_job({'selected': {'file_ids': [first['id'], first['id']], 'container_ids': [key]}})
        self.assertEqual(job['state'], 'ready', job)
        with zipfile.ZipFile(job['path']) as archive:
            self.assertEqual(set(archive.namelist()), {'chosen.txt', 'pdf1.pdf'})
            self.assertEqual(len(PdfReader(io.BytesIO(archive.read('pdf1.pdf'))).pages), 1)
        job = self.wait_job({'selected': {'container_ids': [key]}})
        self.assertEqual(job['state'], 'ready', job)
        with zipfile.ZipFile(job['path']) as archive:
            self.assertEqual(archive.namelist(), ['pdf1.pdf'])

    def test_image_order_rotation_and_cached_pdf_follow_current_tiles(self):
        def split_image(name, left, right):
            from PIL import ImageColor
            with Image.new('RGB', (80, 40), left) as image:
                for x in range(40, 80):
                    for y in range(40):
                        image.putpixel((x, y), ImageColor.getrgb(right))
                data = io.BytesIO()
                image.save(data, 'PNG')
            return self.upload(name, data.getvalue())

        a = split_image('a.png', 'red', 'blue')
        b = split_image('b.png', 'green', 'yellow')
        key = self.create()
        self.add(key, a, b)
        first = self.wait_job({'container_id': key})
        self.assertEqual(first['state'], 'ready', first)
        first_pdf = first['path']
        first_reader = PdfReader(first_pdf)
        self.assertEqual(len(first_reader.pages), 2)
        first_image = first_reader.pages[0].images[0].image
        self.assertEqual(first_image.size, (80, 40))
        self.assertGreater(first_image.getpixel((10, 20))[0], 200)

        self.workspace.action({'action': 'add', 'id': key, 'file_ids': [b['id']], 'before_id': a['id']})
        self.assertEqual(self.workspace.containers[key]['file_ids'], [b['id'], a['id']])
        self.workspace.action({'action': 'add', 'id': key, 'file_ids': [b['id']], 'after_id': a['id']})
        self.assertEqual(self.workspace.containers[key]['file_ids'], [a['id'], b['id']])
        self.workspace.action({'action': 'add', 'id': key, 'file_ids': [b['id']], 'before_id': a['id']})
        reordered = self.wait_job({'container_id': key})
        self.assertEqual(reordered['state'], 'ready', reordered)
        self.assertNotEqual(reordered['path'], first_pdf)
        reordered_image = PdfReader(reordered['path']).pages[0].images[0].image
        self.assertGreater(reordered_image.getpixel((10, 20))[1], 100)

        self.workspace.action({'action': 'rotate', 'id': key, 'file_id': b['id']})
        self.assertEqual(self.workspace.status()['pdf_containers'][0]['rotations'][b['id']], 90)
        rotated = self.wait_job({'container_id': key})
        self.assertEqual(rotated['state'], 'ready', rotated)
        self.assertNotEqual(rotated['path'], reordered['path'])
        rotated_image = PdfReader(rotated['path']).pages[0].images[0].image
        self.assertEqual(rotated_image.size, (40, 80))
        top = rotated_image.getpixel((20, 10))
        bottom = rotated_image.getpixel((20, 70))
        self.assertGreater(top[1], top[0])   # Green left half becomes the top half.
        self.assertGreater(bottom[0], bottom[2])  # Yellow right half becomes the bottom.
        all_job = self.wait_job({'all': True})
        with zipfile.ZipFile(all_job['path']) as archive:
            combined = PdfReader(io.BytesIO(archive.read('pdf1.pdf')))
            self.assertEqual(combined.pages[0].images[0].image.size, (40, 80))
        for _ in range(3):
            self.workspace.action({'action': 'rotate', 'id': key, 'file_id': b['id']})
        self.assertEqual(self.workspace.containers[key]['rotations'], {})
        self.assertEqual(self.wait_job({'container_id': key})['path'], reordered['path'])
        with self.assertRaises(ValueError):
            self.workspace.action({'action': 'add', 'id': key, 'file_ids': [a['id']], 'before_id': 'missing'})
        with self.assertRaises(ValueError):
            self.workspace.action({'action': 'add', 'id': key, 'file_ids': [a['id']], 'before_id': b['id'], 'after_id': b['id']})
        with self.assertRaises(ValueError):
            self.workspace.action({'action': 'rotate', 'id': key, 'file_id': 'missing'})

    def test_invalid_selection_never_falls_back_to_all_files(self):
        photo = self.image()
        key = self.create()
        empty_selection = {'selected': {'container_ids': [key]}}
        with self.assertRaises(ValueError):
            self.workspace.start_export(empty_selection)
        self.add(key, photo)
        for selection in (None, {}, {'file_ids': []}, {'file_ids': 'not-a-list'},
                          {'file_ids': ['missing']}, {'container_ids': [key, 'missing']},
                          {'file_ids': [photo['id']]}):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                self.workspace.start_export({'selected': selection})
        with self.assertRaises(ValueError):
            self.workspace.start_export({'all': True, 'selected': {'container_ids': [key]}})
        self.assertEqual(self.workspace.jobs, {})

    def test_conversion_errors_do_not_publish_partial_download(self):
        bad = self.upload('bad.docx', b'corrupt')
        key = self.create()
        self.add(key, bad)
        with patch('pdf_workspace.convert', side_effect=ValueError('invalid document')):
            job = self.wait_job({'all': True})
        self.assertEqual(job['state'], 'error')
        self.assertNotIn('download_url', job)
        self.assertEqual(self.files.get(bad['id'])['path'].read_bytes(), b'corrupt')
        self.workspace.action({'action': 'delete', 'id': key})
        self.assertEqual(self.wait_job({'all': True})['state'], 'ready')

    def test_close_cancels_active_conversion_and_rejects_new_exports(self):
        file = self.image()
        key = self.create()
        self.add(key, file)
        entered = threading.Event()

        def slow_convert(files, destination, cancel, rotations):
            entered.set()
            self.assertTrue(cancel.wait(3))
            raise ValueError('cancelled')

        with patch('pdf_workspace.convert', side_effect=slow_convert):
            job = self.workspace.start_export({'all': True})
            self.assertTrue(entered.wait(2))
            with self.assertRaisesRegex(ValueError, '上一次'):
                self.workspace.start_export({'all': True})
            self.workspace.close()
        self.assertFalse(self.workspace.worker.is_alive())
        self.assertEqual(self.workspace.get_job(job['id'])['state'], 'error')
        with self.assertRaises(ValueError):
            self.workspace.start_export({'all': True})

    def test_raster_formats_and_multipage_tiff(self):
        for extension, kind in [('jpg', 'JPEG'), ('png', 'PNG'), ('gif', 'GIF'), ('webp', 'WEBP'), ('bmp', 'BMP'), ('avif', 'AVIF')]:
            with self.subTest(kind=kind):
                file = self.image('picture.' + extension, kind)
                destination = self.root / (extension + '.pdf')
                convert([file], destination)
                reader = PdfReader(destination)
                self.assertEqual(len(reader.pages), 1)
                self.assertTrue(reader.pages[0].images)
        buffer = io.BytesIO()
        with Image.new('RGB', (48, 32), 'red') as first, Image.new('RGB', (48, 32), 'blue') as second:
            first.save(buffer, 'TIFF', save_all=True, append_images=[second])
        file = self.upload('pages.tiff', buffer.getvalue())
        destination = self.root / 'tiff.pdf'
        convert([file], destination)
        self.assertEqual(len(PdfReader(destination).pages), 2)

    def test_pdf_merge_all_pages_and_encrypted_failure(self):
        writer = PdfWriter()
        writer.add_blank_page(300, 400)
        data = io.BytesIO()
        writer.write(data)
        first = self.upload('one.pdf', data.getvalue())
        second = self.upload('two.pdf', data.getvalue())
        destination = self.root / 'merged.pdf'
        convert([first, second], destination)
        self.assertEqual(len(PdfReader(destination).pages), 2)
        writer.encrypt('secret')
        data = io.BytesIO()
        writer.write(data)
        encrypted = self.upload('locked.pdf', data.getvalue())
        with self.assertRaisesRegex(ValueError, '密码'):
            convert([encrypted], self.root / 'locked-output.pdf')
        writer.close()


if __name__ == '__main__':
    unittest.main()
