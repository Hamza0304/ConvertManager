import json
from datetime import timedelta

from license_server.models import Plan, utc_now, db


DEFAULT_PLANS = (
    {
        "code": "MONTHLY",
        "name": "Monthly",
        "type": "PERSONAL",
        "price": 19.99,
        "duration_days": 30,
        "max_devices": 2,
        "features": ["2 devices", "Email support", "Monthly updates"],
    },
    {
        "code": "YEARLY",
        "name": "Yearly",
        "type": "PERSONAL",
        "price": 99.99,
        "duration_days": 365,
        "max_devices": 3,
        "features": ["3 devices", "Priority support", "Annual updates"],
    },
    {
        "code": "LIFETIME",
        "name": "Lifetime",
        "type": "PERSONAL",
        "price": 249.99,
        "duration_days": None,
        "max_devices": 5,
        "features": ["5 devices", "Lifetime access", "Premium support"],
    },
)

VALID_TYPES = {"PERSONAL", "COMPANY"}


def normalize_code(value):
    return str(value or "").strip().upper().replace(" ", "-")


def parse_features(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").splitlines() if item.strip()]


def validate_plan_values(data, existing=None):
    code = normalize_code(data.get("code", existing.code if existing else ""))
    name = str(data.get("name", existing.name if existing else "")).strip()
    plan_type = str(data.get("type", existing.type if existing else "PERSONAL")).strip().upper()
    try:
        price = float(data.get("price", existing.price if existing else 0))
    except (TypeError, ValueError) as error:
        raise ValueError("Price must be a valid number.") from error
    try:
        max_devices = int(data.get("max_devices", existing.max_devices if existing else 1))
    except (TypeError, ValueError) as error:
        raise ValueError("Device limit must be a positive integer.") from error
    raw_duration = data.get("duration_days", existing.duration_days if existing else None)
    if raw_duration in (None, "", "LIFETIME", "lifetime"):
        duration_days = None
    else:
        try:
            duration_days = int(raw_duration)
        except (TypeError, ValueError) as error:
            raise ValueError("Duration must be a positive number of days or lifetime.") from error
        if duration_days <= 0:
            raise ValueError("Duration must be a positive number of days or lifetime.")
    if not code:
        raise ValueError("Plan code cannot be empty.")
    if not name:
        raise ValueError("Plan name cannot be empty.")
    if plan_type not in VALID_TYPES:
        raise ValueError("Plan type must be Personal or Company.")
    if price < 0:
        raise ValueError("Price cannot be negative.")
    if max_devices < 1:
        raise ValueError("Device limit must be at least 1.")
    return {
        "code": code,
        "name": name,
        "type": plan_type,
        "price": price,
        "duration_days": duration_days,
        "max_devices": max_devices,
        "features": parse_features(data.get("features", existing.feature_list() if existing else [])),
    }


def plan_payload(plan):
    return {
        "code": plan.code,
        "name": plan.name,
        "type": plan.type,
        "price": plan.price,
        "duration_days": plan.duration_days,
        "max_devices": plan.max_devices,
        "features": plan.feature_list(),
        "active": plan.active,
    }


def ensure_default_plans():
    changed = False
    for values in DEFAULT_PLANS:
        plan = Plan.query.filter_by(code=values["code"]).first()
        if plan is None:
            plan = Plan(**{key: value for key, value in values.items() if key != "features"})
            plan.features = json.dumps(values["features"])
            db.session.add(plan)
            changed = True
    if changed:
        db.session.commit()


def expiration_for_plan(plan, start=None):
    if plan.duration_days is None:
        return None
    return (start or utc_now()) + timedelta(days=plan.duration_days)
