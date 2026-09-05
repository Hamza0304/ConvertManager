import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re


LEGACY_TRIAL_DURATION_DAYS = 7
ENFORCE_APPLICATION_GATE = True
OFFLINE_GRACE_DAYS = 7
LICENSE_KEY_PATTERN = re.compile(r"^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}(?:-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}){3}$")


class LicenseService:
    """Persistent device identity and non-authoritative server-license cache."""

    def __init__(self, storage_path=None, now_provider=None):
        self.storage_path = Path(storage_path) if storage_path else self._default_storage_path()
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now_provider or (lambda: datetime.now(timezone.utc))
        # This is intentionally memory-only. A copied or edited cache must not
        # authorize commercial features after the application is restarted.
        self._server_validated_this_session = False
        self.data = self._load_data()
        self._ensure_device_id()
        self._ensure_trial()
        self._save_data()

    @staticmethod
    def _default_storage_path():
        app_data = os.environ.get("APPDATA")
        if app_data:
            return Path(app_data) / "ConvertManager" / "license.json"
        return Path.home() / ".convertmanager" / "license.json"

    def _load_data(self):
        if not self.storage_path.exists():
            return {}
        try:
            with self.storage_path.open("r", encoding="utf-8") as file:
                value = json.load(file)
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_data(self):
        temporary = self.storage_path.with_suffix(".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as file:
                json.dump(self.data, file, indent=2, ensure_ascii=False)
            temporary.replace(self.storage_path)
        except OSError:
            pass

    def _ensure_device_id(self):
        if not self.data.get("device_id"):
            seed = str(uuid.uuid4())
            self.data["device_id"] = hashlib.sha256(seed.encode()).hexdigest()

    def _ensure_trial(self):
        if self.data.get("license_key"):
            return
        if self._parse_timestamp(self.data.get("trial_started_at")):
            return

        started = self._now()
        expires = started + timedelta(days=LEGACY_TRIAL_DURATION_DAYS)
        self.data["trial_started_at"] = started.isoformat()
        self.data["trial_expires_at"] = expires.isoformat()

    @staticmethod
    def _parse_timestamp(value):
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def normalize_key(key):
        return str(key or "").strip().upper()

    @classmethod
    def is_valid_key_format(cls, key):
        return bool(LICENSE_KEY_PATTERN.fullmatch(cls.normalize_key(key)))

    def get_license(self):
        return dict(self.data)

    def save_license(self, license_data):
        if not isinstance(license_data, dict):
            return False
        self.data.update(license_data)
        self._save_data()
        return True

    def save_server_license(self, response):
        license_data = response.get("license") if isinstance(response, dict) else None
        if not isinstance(license_data, dict):
            return False

        key = self.normalize_key(license_data.get("key") or license_data.get("license_key"))
        if not self.is_valid_key_format(key):
            return False
        if license_data.get("plan") not in {"MONTHLY", "YEARLY", "LIFETIME"}:
            return False
        if license_data.get("device_id", self.get_device_id()) != self.get_device_id():
            return False
        if license_data.get("status", "ACTIVE") not in {"ACTIVE", "EXPIRED", "REVOKED"}:
            return False
        try:
            max_devices = int(license_data.get("max_devices", 0))
            active_devices = int(license_data.get("active_devices", 0))
        except (TypeError, ValueError):
            return False
        if max_devices < 1 or active_devices < 0:
            return False

        self.data.update({
            "license_key": key,
            "plan": license_data["plan"],
            "status": license_data.get("status", "ACTIVE"),
            "activated_at": license_data.get("activated_at"),
            "expires_at": license_data.get("expires_at"),
            "max_devices": max_devices,
            "active_devices": active_devices,
            "device_id": license_data.get("device_id", self.get_device_id()),
            "last_validation_at": self._now().isoformat(),
            "last_validation_status": "ONLINE",
        })
        self._server_validated_this_session = True
        self._save_data()
        return True

    def save_server_free_access(self, response):
        if not isinstance(response, dict):
            return False

        access = response.get("free_access")
        if not isinstance(access, dict):
            return False
        if access.get("device_id") != self.get_device_id():
            return False

        started = self._parse_timestamp(access.get("trial_started_at"))
        expires = self._parse_timestamp(access.get("trial_expires_at"))
        if started is None or expires is None or expires < started:
            return False

        enabled = bool(access.get("enabled"))
        self.data.update({
            "trial_started_at": started.isoformat(),
            "trial_expires_at": expires.isoformat(),
            "free_access_enabled": enabled,
            "free_access_revision": access.get("revision"),
            "last_validation_status": "ONLINE",
            "status": "TRIAL" if enabled and expires > self._now() else "EXPIRED",
        })
        self._save_data()
        return True

    def apply_server_error(self, code):
        if code == "INVALID_LICENSE":
            # The server reached and rejected this key. Drop the stale cache so
            # a newly created Admin key can be entered; do not mark OFFLINE.
            self.deactivate_license()
            return
        statuses = {
            "LICENSE_EXPIRED": "EXPIRED",
            "LICENSE_REVOKED": "REVOKED",
            "DEVICE_NOT_AUTHORIZED": "DEVICE_NOT_AUTHORIZED",
        }
        if code in statuses:
            self.data["status"] = statuses[code]
            self._server_validated_this_session = False
            self._save_data()

    def record_validation_failure(self):
        self.data["last_validation_status"] = "OFFLINE"
        self._save_data()

    def get_last_validation_at(self):
        return self.data.get("last_validation_at")

    def get_connection_status(self):
        return self.data.get("last_validation_status", "NOT_CHECKED")

    def can_use_cached_license(self):
        if self.get_status() != "ACTIVE":
            return False
        validated = self._parse_timestamp(self.get_last_validation_at())
        if validated is None:
            return False
        return self._now() - validated <= timedelta(days=OFFLINE_GRACE_DAYS)

    def activate_license(self, license_key, plan="MONTHLY", expires_at=None):
        """Deprecated compatibility method that never grants local access.

        A commercial license becomes active only when ``save_server_license``
        accepts a successful response from the License Server.
        """
        return False

    def deactivate_license(self):
        self._server_validated_this_session = False
        self.data.pop("license_key", None)
        self.data.pop("plan", None)
        self.data.pop("activated_at", None)
        self.data.pop("expires_at", None)
        self.data.pop("last_validation_at", None)
        self.data.pop("last_validation_status", None)
        self.data.pop("max_devices", None)
        self.data.pop("active_devices", None)
        self._save_data()
        return True

    def get_status(self):
        cached_status = self.data.get("status")
        if cached_status in {"REVOKED", "EXPIRED", "DEVICE_NOT_AUTHORIZED", "INVALID"}:
            return cached_status
        if self.data.get("license_key"):
            if not self.is_valid_key_format(self.data["license_key"]):
                return "INVALID"
            expiration = self._parse_timestamp(self.data.get("expires_at"))
            if self.data.get("plan") != "LIFETIME" and expiration is None:
                return "INVALID"
            if expiration and self._now() >= expiration:
                return "EXPIRED"
            return "ACTIVE"

        expiration = self._parse_timestamp(self.data.get("trial_expires_at"))
        if expiration is None:
            return "INVALID"
        if self.data.get("free_access_enabled") is False:
            return "EXPIRED"
        return "TRIAL" if self._now() < expiration else "EXPIRED"

    def validate_license(self):
        return self.get_status() in {"ACTIVE", "TRIAL"}

    def is_valid(self):
        return self.validate_license()

    def is_expired(self):
        return self.get_status() == "EXPIRED"

    def can_use_application(self):
        if not ENFORCE_APPLICATION_GATE:
            return True
        if self.get_status() == "TRIAL":
            return True
        return self.get_status() == "ACTIVE" and self._server_validated_this_session

    def get_days_remaining(self):
        status = self.get_status()
        if status == "ACTIVE":
            expiration = self._parse_timestamp(self.data.get("expires_at"))
        elif status == "TRIAL":
            expiration = self._parse_timestamp(self.data.get("trial_expires_at"))
        else:
            return 0
        if expiration is None:
            return 0
        remaining = expiration - self._now()
        return max(0, remaining.days + (1 if remaining.seconds else 0))

    def get_device_id(self):
        return self.data["device_id"]

    def get_plan(self):
        return self.data.get("plan", "TRIAL") if self.get_status() != "TRIAL" else "TRIAL"
