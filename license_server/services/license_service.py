import hashlib
import secrets
from datetime import timedelta, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from license_server.models import License, LicenseDevice, db, utc_now


PLANS = {"TRIAL", "MONTHLY", "YEARLY", "LIFETIME"}
ACTIVE_STATUSES = {"ACTIVE", "TRIAL"}
KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MAX_DEVICE_ID_LENGTH = 128
MAX_KEY_GENERATION_ATTEMPTS = 10


def normalize_key(value):
    return str(value or "").strip().upper()


def valid_key_format(value):
    key = normalize_key(value)
    parts = key.split("-")
    return len(parts) == 4 and all(len(part) == 4 and all(character in KEY_ALPHABET for character in part) for part in parts)


def hash_key(value):
    return hashlib.sha256(normalize_key(value).encode("utf-8")).hexdigest()


def generate_key():
    return "-".join("".join(secrets.choice(KEY_ALPHABET) for _ in range(4)) for _ in range(4))


def find_license(key):
    if not valid_key_format(key):
        return None
    return License.query.filter_by(license_key_hash=hash_key(key)).first()


def verify_issued_license(key, record, plan=None, max_devices=None):
    """Confirm the plaintext key matches the just-created License row."""
    if record is None or getattr(record, "id", None) is None:
        raise ValueError("License record was not saved")
    if not valid_key_format(key):
        raise ValueError("Generated license key has an invalid format")
    found = find_license(key)
    if found is None or found.id != record.id:
        raise ValueError("Generated license key could not be looked up")
    if plan is not None and found.plan != str(plan).strip().upper():
        raise ValueError("License plan does not match the order")
    if max_devices is not None and int(found.max_devices) != int(max_devices):
        raise ValueError("License device limit does not match the order")
    if found.status not in {"NOT_ACTIVATED", "ACTIVE"}:
        raise ValueError("License status is not usable")
    return found


def current_status(license_record, now=None):
    now = utc_now() if now is None else now
    if license_record.status == "REVOKED":
        return "REVOKED"
    if license_record.expires_at and now >= license_record.expires_at:
        return "EXPIRED"
    return license_record.status


def active_devices(license_record):
    """Return active device objects for callers that need the records."""
    return [device for device in license_record.devices if device.status == "ACTIVE"]


def _active_device_count(license_id):
    return (
        db.session.query(func.count(LicenseDevice.id))
        .filter(LicenseDevice.license_id == license_id, LicenseDevice.status == "ACTIVE")
        .scalar()
        or 0
    )


def _valid_device_id(device_id):
    return isinstance(device_id, str) and bool(device_id.strip()) and len(device_id.strip()) <= MAX_DEVICE_ID_LENGTH


def _invalid_license_error():
    return None, ("INVALID_LICENSE", "License key was not found.", 404)


def _invalid_device_error():
    return None, ("INVALID_REQUEST", "device_id must be a non-empty value of at most 128 characters.", 400)


def _days_remaining(license_record, status, now):
    expiration = license_record.expires_at
    if license_record.plan == "LIFETIME" and expiration is None:
        return None
    if expiration is None or status not in ACTIVE_STATUSES:
        return 0
    seconds_remaining = (expiration - now).total_seconds()
    if seconds_remaining <= 0:
        return 0
    return int((seconds_remaining + 86399) // 86400)


def serialize_license(license_record, key=None, device=None, now=None):
    now = utc_now() if now is None else now
    status = current_status(license_record, now)
    return {
        "key": key or f"****-****-****-{license_record.license_key_last4}",
        "plan": license_record.plan,
        "status": status,
        "activated_at": _iso(license_record.activated_at),
        "expires_at": _iso(license_record.expires_at),
        "device_id": device.device_id if device else None,
        "days_remaining": _days_remaining(license_record, status, now),
        "max_devices": license_record.max_devices,
        "active_devices": _active_device_count(license_record.id),
    }


def activate(key, device_id):
    if not valid_key_format(key):
        return _invalid_license_error()
    if not _valid_device_id(device_id):
        return _invalid_device_error()
    key, device_id, now = normalize_key(key), device_id.strip(), utc_now()
    license_record = find_license(key)
    if not license_record:
        return _invalid_license_error()
    status = current_status(license_record, now)
    if status == "REVOKED":
        return None, ("LICENSE_REVOKED", "This license has been revoked.", 403)
    if status == "EXPIRED":
        return None, ("LICENSE_EXPIRED", "This license has expired.", 403)
    device = LicenseDevice.query.filter_by(license_id=license_record.id, device_id=device_id).first()
    if device and device.status == "ACTIVE":
        device.last_seen_at = now
        license_record.last_validation_at = now
        db.session.commit()
        return serialize_license(license_record, key, device, now), None
    if _active_device_count(license_record.id) >= license_record.max_devices:
        return None, ("DEVICE_LIMIT_REACHED", "The device limit for this license has been reached.", 409)
    if device is None:
        device = LicenseDevice(license_id=license_record.id, device_id=device_id)
        db.session.add(device)
    device.status = "ACTIVE"
    device.activated_at = now
    device.deactivated_at = None
    device.last_seen_at = now
    license_record.status = "ACTIVE"
    license_record.activated_at = license_record.activated_at or now
    license_record.last_validation_at = now
    db.session.commit()
    return serialize_license(license_record, key, device, now), None


def validate(key, device_id):
    if not valid_key_format(key):
        return _invalid_license_error()
    if not _valid_device_id(device_id):
        return _invalid_device_error()
    key, device_id, now = normalize_key(key), device_id.strip(), utc_now()
    license_record = find_license(key)
    if not license_record:
        return _invalid_license_error()
    status = current_status(license_record, now)
    if status == "REVOKED":
        return None, ("LICENSE_REVOKED", "This license has been revoked.", 403)
    if status == "EXPIRED":
        return None, ("LICENSE_EXPIRED", "This license has expired.", 403)
    device = LicenseDevice.query.filter_by(license_id=license_record.id, device_id=device_id, status="ACTIVE").first()
    if not device:
        return None, ("DEVICE_NOT_AUTHORIZED", "This device is not authorized for the license.", 403)
    device.last_seen_at = now
    license_record.last_validation_at = now
    db.session.commit()
    return serialize_license(license_record, key=key, device=device, now=now), None


def deactivate(key, device_id):
    if not valid_key_format(key):
        return _invalid_license_error()
    if not _valid_device_id(device_id):
        return _invalid_device_error()
    license_record = find_license(key)
    if not license_record:
        return _invalid_license_error()
    device = LicenseDevice.query.filter_by(license_id=license_record.id, device_id=device_id.strip(), status="ACTIVE").first()
    if not device:
        return None, ("DEVICE_NOT_AUTHORIZED", "This device is not active for the license.", 404)
    device.status = "INACTIVE"
    device.deactivated_at = utc_now()
    db.session.commit()
    return {"deactivated": True}, None


def license_info(key, device_id):
    if not valid_key_format(key):
        return _invalid_license_error()
    if not _valid_device_id(device_id):
        return _invalid_device_error()
    key, device_id, now = normalize_key(key), device_id.strip(), utc_now()
    license_record = find_license(key)
    if not license_record:
        return _invalid_license_error()
    device = LicenseDevice.query.filter_by(license_id=license_record.id, device_id=device_id, status="ACTIVE").first()
    if not device:
        return None, ("DEVICE_NOT_AUTHORIZED", "This device is not authorized for the license.", 403)
    return serialize_license(license_record, key=key, device=device, now=now), None


def create_license(plan="MONTHLY", max_devices=1, expires_at=None, customer_name=None, customer_email=None, notes=None):
    normalized_plan = str(plan or "").strip().upper()
    if normalized_plan not in PLANS or normalized_plan == "TRIAL":
        raise ValueError("Invalid commercial license plan")
    if isinstance(max_devices, bool):
        raise ValueError("max_devices must be a positive integer")
    try:
        normalized_max_devices = int(max_devices)
    except (TypeError, ValueError) as error:
        raise ValueError("max_devices must be a positive integer") from error
    if normalized_max_devices <= 0:
        raise ValueError("max_devices must be a positive integer")
    if normalized_plan == "LIFETIME":
        expires_at = None
    elif expires_at is None:
        expires_at = utc_now() + timedelta(days=30 if normalized_plan == "MONTHLY" else 365)
    for _ in range(MAX_KEY_GENERATION_ATTEMPTS):
        key = generate_key()
        record = License(
            license_key_hash=hash_key(key),
            license_key_last4=key[-4:],
            plan=normalized_plan,
            status="NOT_ACTIVATED",
            max_devices=normalized_max_devices,
            expires_at=expires_at,
            customer_name=customer_name,
            customer_email=customer_email,
            notes=notes,
        )
        db.session.add(record)
        try:
            db.session.commit()
        except IntegrityError:
            # The unique hash constraint also protects against a concurrent collision.
            db.session.rollback()
            continue
        return key, record
    raise RuntimeError("Unable to generate a unique license key")


def _iso(value):
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


@public_bp.get("/download/ConvertManager-Setup.exe")
def download_convertmanager():
    return send_from_directory(
        current_app.config["DOWNLOAD_DIR"],
        "ConvertManager-Setup.exe",
        as_attachment=True
    )