import logging
import time
from collections import defaultdict, deque
from datetime import datetime
from functools import wraps

from flask import Blueprint, current_app, jsonify, request

from license_server.models import License, LicenseDevice, Plan, db, utc_now
from license_server.services.free_access_service import access_payload, register_or_refresh
from license_server.services.license_service import (
    activate,
    create_license,
    deactivate,
    find_license,
    license_info,
    normalize_key,
    validate,
)


logger = logging.getLogger(__name__)
license_bp = Blueprint("license", __name__, url_prefix="/api/license")
_requests = defaultdict(deque)


def _error(code, message, status):
    return jsonify({"success": False, "error": code, "message": message}), status


def _payload():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None
    return payload


def rate_limited():
    now = time.monotonic()
    address = request.remote_addr or "unknown"
    entries = _requests[address]
    window = current_app.config["RATE_LIMIT_WINDOW_SECONDS"]
    maximum = current_app.config["RATE_LIMIT_MAX_REQUESTS"]
    while entries and now - entries[0] >= window:
        entries.popleft()
    if len(entries) >= maximum:
        logger.warning("Rate limit triggered for masked address %s", address[:3] + "***")
        return True
    entries.append(now)
    return False


def require_admin(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        configured = current_app.config.get("LICENSE_ADMIN_TOKEN", "")
        supplied = request.headers.get("X-Admin-Token", "")
        if not configured or supplied != configured:
            return _error("ADMIN_UNAUTHORIZED", "Administrator authentication required.", 401)
        return function(*args, **kwargs)
    return wrapped


def _license_response(data, status=200):
    return jsonify({"success": True, "license": data, **data}), status


@license_bp.post("/activate")
def activate_route():
    if rate_limited():
        return _error("RATE_LIMITED", "Too many requests. Please try again later.", 429)
    payload = _payload()
    if not payload or not payload.get("license_key") or not payload.get("device_id"):
        return _error("INVALID_REQUEST", "license_key and device_id are required.", 400)
    data, error = activate(normalize_key(payload["license_key"]), str(payload["device_id"]))
    if error:
        logger.info("License activation rejected: %s", error[0])
        return _error(*error)
    logger.info("License activated for masked device")
    return _license_response(data)


@license_bp.post("/validate")
def validate_route():
    if rate_limited():
        return _error("RATE_LIMITED", "Too many requests. Please try again later.", 429)
    payload = _payload()
    if not payload or not payload.get("license_key") or not payload.get("device_id"):
        return _error("INVALID_REQUEST", "license_key and device_id are required.", 400)
    data, error = validate(normalize_key(payload["license_key"]), str(payload["device_id"]))
    if error:
        logger.info("License validation rejected: %s", error[0])
        return _error(*error)
    return _license_response(data)


@license_bp.post("/deactivate")
def deactivate_route():
    payload = _payload()
    if not payload or not payload.get("license_key") or not payload.get("device_id"):
        return _error("INVALID_REQUEST", "license_key and device_id are required.", 400)
    data, error = deactivate(normalize_key(payload["license_key"]), str(payload["device_id"]))
    if error:
        return _error(*error)
    logger.info("License device deactivated")
    return jsonify({"success": True, **data})


@license_bp.post("/free-access")
def free_access_route():
    if rate_limited():
        return _error("RATE_LIMITED", "Too many requests. Please try again later.", 429)
    payload = _payload()
    device_id = str(payload.get("device_id", "")).strip() if payload else ""
    if not device_id or len(device_id) > 128:
        return _error("INVALID_REQUEST", "device_id is required.", 400)
    settings, grant = register_or_refresh(device_id, payload.get("trial_started_at"))
    return jsonify({"success": True, "free_access": access_payload(settings, grant)})


@license_bp.get("/plans")
def plans_route():
    records = Plan.query.filter_by(active=True).order_by(Plan.price.asc(), Plan.name.asc()).all()
    return jsonify({
        "success": True,
        "plans": [
            {
                "code": plan.code,
                "name": plan.name,
                "type": plan.type,
                "price": plan.price,
                "duration_days": plan.duration_days,
                "max_devices": plan.max_devices,
                "features": plan.feature_list(),
                "active": plan.active,
            }
            for plan in records
        ],
    })


@license_bp.route("/info", methods=["GET", "POST"])
def info_route():
    payload = _payload() if request.method == "POST" else request.args
    if not payload or not payload.get("license_key") or not payload.get("device_id"):
        return _error("INVALID_REQUEST", "license_key and device_id are required.", 400)
    data, error = license_info(normalize_key(payload["license_key"]), str(payload["device_id"]))
    if error:
        return _error(*error)
    return _license_response(data)


@license_bp.post("/admin/licenses")
@require_admin
def admin_create():
    payload = _payload() or {}
    try:
        expires_at = _parse_date(payload.get("expires_at"))
        key, record = create_license(
            plan=payload.get("plan", "MONTHLY"),
            max_devices=payload.get("max_devices", 1),
            expires_at=expires_at,
            customer_name=payload.get("customer_name"),
            customer_email=payload.get("customer_email"),
            notes=payload.get("notes"),
        )
    except (TypeError, ValueError) as error:
        return _error("INVALID_REQUEST", str(error), 400)
    return jsonify({"success": True, "license_key": key, "license": {"id": record.id, "plan": record.plan, "status": record.status}}), 201


@license_bp.get("/admin/licenses")
@require_admin
def admin_list():
    records = License.query.order_by(License.created_at.desc()).all()
    return jsonify({"success": True, "licenses": [_admin_summary(record) for record in records]})


@license_bp.get("/admin/licenses/<int:license_id>")
@require_admin
def admin_view(license_id):
    record = db.session.get(License, license_id)
    if not record:
        return _error("NOT_FOUND", "License was not found.", 404)
    return jsonify({"success": True, "license": _admin_summary(record, include_devices=True)})


@license_bp.post("/admin/licenses/<int:license_id>/revoke")
@require_admin
def admin_revoke(license_id):
    record = db.session.get(License, license_id)
    if not record:
        return _error("NOT_FOUND", "License was not found.", 404)
    record.status = "REVOKED"
    db.session.commit()
    return jsonify({"success": True})


@license_bp.post("/admin/licenses/<int:license_id>/reactivate")
@require_admin
def admin_reactivate(license_id):
    record = db.session.get(License, license_id)
    if not record:
        return _error("NOT_FOUND", "License was not found.", 404)
    record.status = "ACTIVE"
    db.session.commit()
    return jsonify({"success": True})


@license_bp.patch("/admin/licenses/<int:license_id>")
@require_admin
def admin_update(license_id):
    record = db.session.get(License, license_id)
    if not record:
        return _error("NOT_FOUND", "License was not found.", 404)

    payload = _payload() or {}
    try:
        if "max_devices" in payload:
            record.max_devices = max(1, int(payload["max_devices"]))
        if "expires_at" in payload:
            record.expires_at = _parse_date(payload["expires_at"])
    except (TypeError, ValueError) as error:
        return _error("INVALID_REQUEST", str(error), 400)

    db.session.commit()
    return jsonify({"success": True, "license": _admin_summary(record)})


@license_bp.post("/admin/licenses/<int:license_id>/deactivate-device")
@require_admin
def admin_deactivate_device(license_id):
    payload = _payload() or {}
    device = LicenseDevice.query.filter_by(license_id=license_id, device_id=payload.get("device_id"), status="ACTIVE").first()
    if not device:
        return _error("NOT_FOUND", "Active device was not found.", 404)
    device.status = "INACTIVE"
    device.deactivated_at = utc_now()
    db.session.commit()
    return jsonify({"success": True})


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    raise ValueError("expires_at must be an ISO 8601 date")


def _admin_summary(record, include_devices=False):
    data = {
        "id": record.id,
        "key_last4": record.license_key_last4,
        "plan": record.plan,
        "status": record.status,
        "max_devices": record.max_devices,
        "active_devices": LicenseDevice.query.filter_by(license_id=record.id, status="ACTIVE").count(),
        "created_at": record.created_at.isoformat() + "Z",
        "expires_at": record.expires_at.isoformat() + "Z" if record.expires_at else None,
        "customer_name": record.customer_name,
        "customer_email": record.customer_email,
    }
    if include_devices:
        data["devices"] = [
            {"device_id": device.device_id, "status": device.status, "last_seen_at": device.last_seen_at.isoformat() + "Z" if device.last_seen_at else None}
            for device in record.devices
        ]
    return data
