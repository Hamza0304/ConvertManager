from datetime import datetime, timezone

from license_server.models import FreeAccessGrant, FreeAccessSetting, db, utc_now


def get_settings():
    settings = FreeAccessSetting.query.first()
    if settings is None:
        settings = FreeAccessSetting(enabled=True, duration_days=30, revision=1)
        db.session.add(settings)
        db.session.commit()
    return settings


def _normalize_started_at(value):
    if not value:
        return utc_now()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return utc_now()
    parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    now = utc_now()
    return min(parsed, now)


def register_or_refresh(device_id, started_at=None):
    settings = get_settings()
    grant = FreeAccessGrant.query.filter_by(device_id=device_id).first()
    now = utc_now()
    if grant is None:
        started = _normalize_started_at(started_at)
        grant = FreeAccessGrant(
            device_id=device_id,
            started_at=started,
            applied_duration_days=settings.duration_days,
        )
        db.session.add(grant)
    elif grant.applied_duration_days < settings.duration_days:
        if grant.expires_at is None:
            grant.expires_at = grant.started_at
        from datetime import timedelta
        grant.expires_at += timedelta(days=settings.duration_days - grant.applied_duration_days)
        grant.applied_duration_days = settings.duration_days
    if grant.expires_at is None:
        from datetime import timedelta
        grant.expires_at = grant.started_at + timedelta(days=settings.duration_days)
    grant.last_seen_at = now
    db.session.commit()
    return settings, grant


def extend_existing_grants(previous_duration, new_duration):
    if new_duration <= previous_duration:
        return 0
    from datetime import timedelta
    changed = 0
    for grant in FreeAccessGrant.query.filter(FreeAccessGrant.applied_duration_days < new_duration).all():
        current_duration = max(previous_duration, grant.applied_duration_days)
        grant.expires_at = (grant.expires_at or grant.started_at) + timedelta(days=new_duration - current_duration)
        grant.applied_duration_days = new_duration
        changed += 1
    return changed


def access_payload(settings, grant):
    return {
        "enabled": settings.enabled,
        "duration_days": settings.duration_days,
        "revision": settings.revision,
        "device_id": grant.device_id,
        "trial_started_at": grant.started_at.isoformat() + "Z",
        "trial_expires_at": grant.expires_at.isoformat() + "Z" if grant.expires_at else None,
        "status": "TRIAL" if settings.enabled and grant.expires_at and grant.expires_at > utc_now() else "EXPIRED",
    }
