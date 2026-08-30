import tempfile
import threading
import unittest
from pathlib import Path

from PIL import Image

from app.services.conversion_service import convert_files
from app.utils.file_detector import detect_format, is_supported


class ConverterTests(unittest.TestCase):

    def test_format_detection_supports_core_formats(self):
        self.assertEqual(detect_format("photo.tiff"), "TIFF")
        self.assertEqual(detect_format("report.pdf"), "PDF")
        self.assertTrue(is_supported("archive.zip"))

    def test_image_to_pdf_does_not_modify_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "photo.png"
            output = root / "output"
            Image.new("RGB", (4, 4), "red").save(source)

            result = convert_files([str(source)], "PDF", output)

            self.assertEqual(result["successful"], 1)
            self.assertTrue((output / "photo.pdf").exists())
            self.assertTrue(source.exists())

    def test_pdf_to_docx_creates_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.png"
            output = root / "output"
            Image.new("RGB", (120, 80), "white").save(source)
            convert_files([str(source)], "PDF", output)

            result = convert_files([str(output / "report.pdf")], "DOCX", output)

            self.assertEqual(result["successful"], 1)
            self.assertTrue((output / "report.docx").exists())

    def test_pdf_to_txt_creates_text_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.png"
            output = root / "output"
            Image.new("RGB", (120, 80), "white").save(source)
            convert_files([str(source)], "PDF", output)

            result = convert_files([str(output / "report.pdf")], "TXT", output)

            self.assertEqual(result["successful"], 1)
            self.assertTrue((output / "report.txt").exists())

    def test_failed_file_does_not_stop_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = root / "good.png"
            bad = root / "bad.png"
            output = root / "output"
            Image.new("RGB", (4, 4), "blue").save(good)
            bad.write_text("not an image", encoding="utf-8")

            result = convert_files([str(good), str(bad)], "JPG", output)

            self.assertEqual(result["successful"], 1)
            self.assertEqual(result["failed"], 1)
            self.assertTrue((output / "good.jpg").exists())
            self.assertTrue(good.exists())
            self.assertTrue(bad.exists())

    def test_create_copy_and_skip_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "photo.png"
            output = root / "output"
            Image.new("RGB", (4, 4), "green").save(source)

            first = convert_files([str(source)], "JPG", output)
            second = convert_files([str(source)], "JPG", output, file_handling="create_copy")
            third = convert_files([str(source)], "JPG", output, file_handling="skip")

            self.assertEqual(first["successful"], 1)
            self.assertTrue((output / "photo (1).jpg").exists())
            self.assertEqual(second["successful"], 1)
            self.assertEqual(third["skipped"], 1)
            self.assertEqual(third["successful"], 0)

    def test_conversion_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "photo.png"
            output = root / "output"
            Image.new("RGB", (4, 4), "purple").save(source)
            cancel_event = threading.Event()

            def progress(current, total):
                cancel_event.set()

            result = convert_files(
                [str(source), str(source)],
                "JPG",
                output,
                progress_callback=progress,
                cancel_event=cancel_event
            )

            self.assertTrue(result["cancelled"])
            self.assertEqual(result["successful"], 1)


if __name__ == "__main__":
    unittest.main()