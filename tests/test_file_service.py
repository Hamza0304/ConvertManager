import tempfile
import threading
import unittest
from pathlib import Path

from app.services.file_service import import_dropped_items, import_files, scan_folder


class FileServiceTests(unittest.TestCase):

    def test_import_files_reports_progress_without_copying(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "large.bin"
            source.write_bytes(b"x" * (1024 * 1024))
            updates = []

            imported, errors, cancelled = import_files(
                [source],
                progress_callback=lambda current, total, path: updates.append(
                    (current, total, path)
                )
            )

            self.assertEqual(imported, [])
            self.assertEqual(len(errors), 1)
            self.assertFalse(cancelled)
            self.assertEqual(updates[-1][0:2], (1, 1))
            self.assertTrue(source.exists())

    def test_import_files_accepts_supported_files_and_rejects_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            supported = root / "photo.png"
            supported.write_bytes(b"not decoded during import")
            missing = root / "missing.png"

            imported, errors, cancelled = import_files([supported, missing])

            self.assertEqual(imported, [str(supported)])
            self.assertEqual(len(errors), 1)
            self.assertFalse(cancelled)

    def test_recursive_scan_finds_supported_files_and_skips_symlink_dirs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            supported = nested / "report.pdf"
            supported.write_bytes(b"pdf")
            unsupported = nested / "notes.exe"
            unsupported.write_bytes(b"exe")
            updates = []

            imported, errors, cancelled = scan_folder(
                root,
                recursive=True,
                progress_callback=lambda current, total, path: updates.append(path)
            )

            self.assertEqual(imported, [str(supported)])
            self.assertEqual(errors, [])
            self.assertFalse(cancelled)
            self.assertEqual(len(updates), 2)

    def test_import_can_be_cancelled_without_partial_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = []
            for index in range(3):
                path = root / f"file{index}.png"
                path.write_bytes(b"image")
                files.append(path)

            cancel_event = threading.Event()

            def progress(current, total, path):
                cancel_event.set()

            imported, errors, cancelled = import_files(
                files,
                cancel_event=cancel_event,
                progress_callback=progress
            )

            self.assertEqual(imported, [str(files[0])])
            self.assertEqual(errors, [])
            self.assertTrue(cancelled)
            self.assertTrue(all(path.exists() for path in files))

    def test_dropped_supported_file_is_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "photo.jpg"
            source.write_bytes(b"image")

            imported, errors, cancelled = import_dropped_items([source])

            self.assertEqual(imported, [str(source)])
            self.assertEqual(errors, [])
            self.assertFalse(cancelled)


if __name__ == "__main__":
    unittest.main()
