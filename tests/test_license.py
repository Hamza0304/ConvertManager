import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.license_service import LicenseService


class LicenseServiceTests(unittest.TestCase):

    def test_new_installation_creates_persistent_trial(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "license.json"
            now = datetime(2026, 8, 28, tzinfo=timezone.utc)
            service = LicenseService(path, lambda: now)
            first = service.get_license()
            restarted = LicenseService(path, lambda: now + timedelta(days=1))

            self.assertEqual(service.get_status(), "TRIAL")
            self.assertEqual(first["trial_started_at"], restarted.get_license()["trial_started_at"])
            self.assertEqual(restarted.get_days_remaining(), 6)
            self.assertEqual(service.get_device_id(), restarted.get_device_id())

    def test_trial_expires_using_actual_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "license.json"
            now = datetime(2026, 8, 28, tzinfo=timezone.utc)
            service = LicenseService(path, lambda: now)
            service._now = lambda: now + timedelta(days=8)
            self.assertEqual(service.get_status(), "EXPIRED")
            self.assertFalse(service.can_use_application())

    def test_local_activation_cannot_grant_a_commercial_license(self):
        with tempfile.TemporaryDirectory() as directory:
            service = LicenseService(Path(directory) / "license.json")
            self.assertFalse(service.activate_license("ABCD-2345-EFGH-6789", "YEARLY"))
            self.assertEqual(service.get_status(), "TRIAL")
            self.assertTrue(service.is_valid())

    def test_invalid_key_and_corrupt_data_fail_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "license.json"
            path.write_text("{invalid", encoding="utf-8")
            service = LicenseService(path)
            self.assertEqual(service.get_status(), "TRIAL")
            self.assertFalse(service.activate_license("bad-key"))

            service.data["trial_expires_at"] = "invalid-date"
            self.assertEqual(service.get_status(), "INVALID")
            self.assertFalse(service.can_use_application())

    def test_license_data_is_separate_from_history(self):
        with tempfile.TemporaryDirectory() as directory:
            license_path = Path(directory) / "license.json"
            history_path = Path(directory) / "history.json"
            service = LicenseService(license_path)
            history_path.write_text(json.dumps([{"files": 2}]), encoding="utf-8")
            self.assertFalse(service.activate_license("ABCD-2345-EFGH-6789", "LIFETIME"))
            self.assertTrue(history_path.exists())
            self.assertTrue(license_path.exists())

    def test_server_license_is_cached_for_offline_grace(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 28, tzinfo=timezone.utc)
            service = LicenseService(Path(directory) / "license.json", lambda: now)
            response = {
                "success": True,
                "license": {
                    "key": "ABCD-2345-EFGH-6789",
                    "plan": "MONTHLY",
                    "status": "ACTIVE",
                    "activated_at": now.isoformat(),
                    "expires_at": (now + timedelta(days=30)).isoformat(),
                    "device_id": service.get_device_id(),
                    "max_devices": 1,
                    "active_devices": 1,
                },
            }
            self.assertTrue(service.save_server_license(response))
            service.record_validation_failure()
            self.assertTrue(service.can_use_cached_license())
            self.assertTrue(service.can_use_application())

            restarted = LicenseService(Path(directory) / "license.json", lambda: now)
            self.assertFalse(restarted.can_use_application())

    def test_server_license_with_wrong_device_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            service = LicenseService(Path(directory) / "license.json")
            response = {
                "success": True,
                "license": {
                    "key": "ABCD-2345-EFGH-6789",
                    "plan": "MONTHLY",
                    "status": "ACTIVE",
                    "device_id": "different-device",
                },
            }
            self.assertFalse(service.save_server_license(response))

    def test_invalid_license_clears_stale_commercial_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 28, tzinfo=timezone.utc)
            service = LicenseService(Path(directory) / "license.json", lambda: now)
            self.assertTrue(service.save_server_license({
                "success": True,
                "license": {
                    "key": "ABCD-2345-EFGH-6789",
                    "plan": "MONTHLY",
                    "status": "ACTIVE",
                    "activated_at": now.isoformat(),
                    "expires_at": (now + timedelta(days=30)).isoformat(),
                    "device_id": service.get_device_id(),
                    "max_devices": 1,
                    "active_devices": 1,
                },
            }))
            service.apply_server_error("INVALID_LICENSE")
            self.assertIsNone(service.get_license().get("license_key"))
            self.assertEqual(service.get_status(), "TRIAL")
            self.assertNotEqual(service.get_connection_status(), "OFFLINE")


if __name__ == "__main__":
    unittest.main()
