import io
import json
import unittest
from urllib.error import URLError

from app.services.license_api import LicenseAPI, LicenseAPIError


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class LicenseAPITests(unittest.TestCase):

    def test_successful_activation_sends_expected_payload(self):
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return FakeResponse({"success": True, "license": {"status": "ACTIVE"}})

        response = LicenseAPI("https://license.test/api", opener=opener).activate_license("KEY", "DEVICE")

        self.assertTrue(response["success"])
        self.assertEqual(requests[0][0].full_url, "https://license.test/api/activate")
        self.assertEqual(json.loads(requests[0][0].data), {"license_key": "KEY", "device_id": "DEVICE"})

    def test_server_error_code_is_preserved(self):
        def opener(request, timeout):
            return FakeResponse({"success": False, "error": {"code": "LICENSE_EXPIRED", "message": "License has expired."}})

        with self.assertRaises(LicenseAPIError) as raised:
            LicenseAPI("https://license.test/api", opener=opener).validate_license("KEY", "DEVICE")

        self.assertEqual(raised.exception.code, "LICENSE_EXPIRED")
        self.assertEqual(str(raised.exception), "License has expired.")

    def test_flat_api_error_contract_is_preserved(self):
        def opener(request, timeout):
            return FakeResponse({"success": False, "error": "DEVICE_LIMIT_REACHED", "message": "No slots left."})

        with self.assertRaises(LicenseAPIError) as raised:
            LicenseAPI(opener=opener).activate_license("KEY", "DEVICE")

        self.assertEqual(raised.exception.code, "DEVICE_LIMIT_REACHED")
        self.assertEqual(str(raised.exception), "No slots left.")

    def test_network_failure_is_friendly(self):
        def opener(request, timeout):
            raise URLError("offline")

        with self.assertRaises(LicenseAPIError) as raised:
            LicenseAPI(opener=opener).get_license_info("KEY", "DEVICE")

        self.assertEqual(raised.exception.code, "NETWORK_ERROR")
        self.assertEqual(str(raised.exception), "Unable to connect to the license server.")

    def test_malformed_response_is_rejected(self):
        def opener(request, timeout):
            return FakeResponse({"unexpected": True})

        with self.assertRaises(LicenseAPIError) as raised:
            LicenseAPI(opener=opener).deactivate_license("KEY", "DEVICE")

        self.assertEqual(raised.exception.code, "SERVER_ERROR")

    def test_malformed_json_is_rejected(self):
        response = io.BytesIO(b"not-json")
        response.__enter__ = lambda: response
        response.__exit__ = lambda *args: False

        def opener(request, timeout):
            return response

        with self.assertRaises(LicenseAPIError) as raised:
            LicenseAPI(opener=opener).validate_license("KEY", "DEVICE")

        self.assertEqual(raised.exception.code, "SERVER_ERROR")


if __name__ == "__main__":
    unittest.main()
