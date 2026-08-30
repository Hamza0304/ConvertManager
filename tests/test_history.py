import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import history_service


class HistoryServiceTests(unittest.TestCase):

    def test_clear_history_keeps_output_files(self):
        with tempfile.TemporaryDirectory() as directory:
            history_file = Path(directory) / "history.json"
            output_file = Path(directory) / "converted.png"
            output_file.write_text("output", encoding="utf-8")
            history_file.write_text(
                json.dumps([{"output_folder": str(output_file.parent)}]),
                encoding="utf-8"
            )

            with patch.object(history_service, "HISTORY_FILE", history_file):
                self.assertEqual(history_service.clear_history(), [])
                self.assertEqual(history_service.load_history(), [])

            self.assertTrue(output_file.exists())

    def test_delete_one_history_record(self):
        with tempfile.TemporaryDirectory() as directory:
            history_file = Path(directory) / "history.json"
            history_file.write_text(
                json.dumps([{"id": 1}, {"id": 2}]),
                encoding="utf-8"
            )

            with patch.object(history_service, "HISTORY_FILE", history_file):
                self.assertTrue(history_service.delete_history_record(0))
                self.assertEqual(history_service.load_history(), [{"id": 2}])

    def test_missing_and_corrupted_history_are_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            history_file = Path(directory) / "history.json"

            with patch.object(history_service, "HISTORY_FILE", history_file):
                self.assertEqual(history_service.load_history(), [])
                history_file.write_text("{invalid", encoding="utf-8")
                self.assertEqual(history_service.load_history(), [])


if __name__ == "__main__":
    unittest.main()