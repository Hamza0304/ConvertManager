import json
import logging
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


LICENSE_API_URL = os.environ.get(
    "CONVERTMANAGER_LICENSE_API_URL",
    "http://127.0.0.1:5000/api/license",
)
DEFAULT_TIMEOUT_SECONDS = 10
logger = logging.getLogger("convertmanager.license")


@dataclass
class LicenseAPIError(Exception):
    code: str
    message: str
    status_code: int | None = None

    def __str__(self):
        return self.message


class LicenseAPI:
    """HTTP client for the ConvertManager License Server API."""

    def __init__(self, base_url=LICENSE_API_URL, timeout=DEFAULT_TIMEOUT_SECONDS, opener=None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = opener or urlopen

    def activate_license(self, license_key, device_id):
        return self._post("/activate", {
            "license_key": license_key,
            "device_id": device_id,
        })

    def validate_license(self, license_key, device_id):
        return self._post("/validate", {
            "license_key": license_key,
            "device_id": device_id,
        })

    def deactivate_license(self, license_key, device_id):
        return self._post("/deactivate", {
            "license_key": license_key,
            "device_id": device_id,
        })

    def get_license_info(self, license_key, device_id):
        return self._post("/info", {
            "license_key": license_key,
            "device_id": device_id,
        })

    def _post(self, endpoint, payload):
        url = f"{self.base_url}{endpoint}"
        logger.info("License API request: POST %s (key=%s, device=%s)", url, _mask(payload.get("license_key")), _mask(payload.get("device_id")))
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )

        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = response.read()
                logger.info("License API response: POST %s status=%s", url, getattr(response, "status", "unknown"))
        except HTTPError as error:
            response_data = self._decode_response(error)
            logger.warning("License API HTTP error: POST %s status=%s response=%s", url, error.code, _safe_log_data(response_data))
            raise self._error_from_response(response_data, error.code) from error
        except (URLError, TimeoutError, OSError) as error:
            logger.warning("License API network error: POST %s error=%s", url, error)
            raise LicenseAPIError(
                "NETWORK_ERROR",
                "Unable to connect to the license server.",
            ) from error

        try:
            response_data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LicenseAPIError(
                "SERVER_ERROR",
                "The license server returned an invalid response.",
            ) from error

        if not isinstance(response_data, dict):
            raise LicenseAPIError("SERVER_ERROR", "The license server returned an invalid response.")
        if not response_data.get("success"):
            logger.warning("License API rejected request: POST %s response=%s", url, _safe_log_data(response_data))
            raise self._error_from_response(response_data)

        logger.info("License API successful response: POST %s response=%s", url, _safe_log_data(response_data))
        return response_data

    @staticmethod
    def _decode_response(response):
        try:
            raw = response.read()
            value = json.loads(raw.decode("utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _error_from_response(data, status_code=None):
        error = data.get("error", {}) if isinstance(data, dict) else {}
        if isinstance(error, str):
            return LicenseAPIError(
                error,
                data.get("message", "The license server rejected the request."),
                status_code,
            )
        code = error.get("code", "SERVER_ERROR")
        message = error.get("message", "The license server rejected the request.")
        return LicenseAPIError(code, message, status_code)


def _mask(value):
    value = str(value or "")
    return f"...{value[-4:]}" if len(value) > 4 else "****"


def _safe_log_data(data):
    """Mask sensitive values before a server payload reaches a local log."""
    if not isinstance(data, dict):
        return data
    return {
        key: _mask(value) if key in {"key", "license_key", "device_id"} else _safe_log_data(value)
        for key, value in data.items()
    }
