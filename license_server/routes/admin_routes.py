import json
import secrets
from datetime import datetime
from functools import wraps

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import case, func
from sqlalchemy.orm import joinedload
from werkzeug.security import check_password_hash, generate_password_hash

from license_server.models import AdminUser, AuditLog, License, LicenseDevice, LicenseOrder, db, utc_now
from license_server.services.email_service import (
    is_email_configured,
    send_license_email,
    send_order_notification,
    smtp_runtime_diagnostics,
)
from license_server.services.license_service import create_license, verify_issued_license, find_license

PLAN_MAX_DEVICES = {
    "MONTHLY": 1,
    "YEARLY": 3,
    "LIFETIME": 5,
}


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def check_csrf():
    sent = request.form.get("csrf_token") or ""
    expected = session.get("csrf_token") or ""
    if not sent or not expected:
        return False
    try:
        return secrets.compare_digest(sent, expected)
    except (TypeError, ValueError):
        return False


def _requested_next():
    return request.form.get("next") or request.args.get("next")


def _safe_admin_next(value):
    """Allow only same-origin admin paths. Reject scheme-relative and external URLs."""
    fallback = url_for("admin.dashboard")
    if not value or not isinstance(value, str):
        return fallback
    candidate = value.strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return fallback
    if "://" in candidate or "\\" in candidate or "\n" in candidate or "\r" in candidate:
        return fallback
    path = candidate.split("?", 1)[0].split("#", 1)[0]
    if path.rstrip("/") == "/admin/login":
        return fallback
    if path != "/admin" and not path.startswith("/admin/"):
        return fallback
    return candidate


def _login_page_redirect():
    next_url = _requested_next()
    if next_url:
        return redirect(url_for("admin.login", next=next_url))
    return redirect(url_for("admin.login"))


def login_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not session.get("admin_user_id"):
            return redirect(url_for("admin.login", next=request.path))
        return function(*args, **kwargs)
    return wrapped


@admin_bp.get("/smtp-status")
@login_required
def smtp_status():
    """Safe SMTP diagnostics for the same runtime as Send License by Email."""
    return jsonify(smtp_runtime_diagnostics())


def _order_license_keys():
    stored = session.get("order_license_keys")
    return stored if isinstance(stored, dict) else {}


def _remember_order_license_key(order_id, key):
    stored = _order_license_keys()
    stored[str(order_id)] = key
    session["order_license_keys"] = stored
    session.modified = True


def _recall_order_license_key(order_id):
    return _order_license_keys().get(str(order_id))


def _fulfill_paid_order(order):
    """Mark payment received and issue a license through create_license() only."""
    if order.status == "REJECTED":
        raise ValueError("Rejected orders cannot be marked as paid.")
    if order.license_id is not None:
        return None, db.session.get(License, order.license_id)

    max_devices = order.max_devices or PLAN_MAX_DEVICES.get(order.plan, 1)
    key, created_license = create_license(
        plan=order.plan,
        max_devices=max_devices,
        customer_name=order.customer_name,
        customer_email=order.customer_email,
        notes=order.notes,
    )
    try:
        verify_issued_license(key, created_license, plan=order.plan, max_devices=max_devices)
    except Exception as error:
        current_app.logger.error(
            "Order %s license verification failed last4=%s error=%s",
            order.id,
            getattr(created_license, "license_key_last4", "????"),
            error,
        )
        db.session.delete(created_license)
        db.session.commit()
        raise

    if order.payment_status != "PAID":
        order.payment_status = "PAID"
        order.paid_at = order.paid_at or utc_now()
    order.license_id = created_license.id
    order.status = "COMPLETED"
    order.approved_at = utc_now()
    order.completed_at = utc_now()
    db.session.commit()
    _remember_order_license_key(order.id, key)
    return key, created_license


def audit(action, license_id=None, device_id=None, metadata=None):
    db.session.add(AuditLog(
        admin_user_id=session.get("admin_user_id"),
        action=action,
        license_id=license_id,
        device_id=device_id,
        ip_address=request.remote_addr,
        metadata_json=json.dumps(metadata or {}),
    ))
    db.session.commit()


@admin_bp.context_processor
def inject_csrf():
    return {"csrf_token": csrf_token}

@admin_bp.get("/login/")
@admin_bp.get("/login")
def login():
    next_url = _safe_admin_next(request.args.get("next"))
    if session.get("admin_user_id"):
        return redirect(next_url)
    return render_template("admin/login.html", next_url=next_url)


@admin_bp.post("/login")
def login_post():
    if not check_csrf():
        flash("Invalid security token.")
        return _login_page_redirect()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    user = AdminUser.query.filter_by(email=email).first()
    if not user or not user.is_active or not check_password_hash(user.password_hash, password):
        flash("Invalid email or password.")
        return _login_page_redirect()
    session.clear()
    session["admin_user_id"] = user.id
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = True
    session.modified = True
    user.last_login_at = utc_now()
    db.session.commit()
    audit("ADMIN_LOGIN")
    return redirect(_safe_admin_next(_requested_next()))


@admin_bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@admin_bp.get("/")
@login_required
def dashboard():
    now = utc_now()
    metrics = db.session.query(
        func.count(License.id).label("total"),
        func.coalesce(func.sum(case(((License.status == "ACTIVE") & ((License.expires_at.is_(None)) | (License.expires_at > now)), 1), else_=0)), 0).label("active"),
        func.coalesce(func.sum(case(((License.status != "REVOKED") & (License.expires_at.is_not(None)) & (License.expires_at <= now), 1), else_=0)), 0).label("expired"),
        func.coalesce(func.sum(case((License.status == "REVOKED", 1), else_=0)), 0).label("revoked"),
    ).one()
    active_devices = LicenseDevice.query.filter_by(status="ACTIVE").count()
    pending_orders = LicenseOrder.query.filter_by(status="PENDING").count()
    return render_template(
        "admin/dashboard.html",
        metrics=metrics,
        active_devices=active_devices,
        pending_orders=pending_orders,
    )


@admin_bp.get("/dashboard")
@login_required
def dashboard_page():
    return redirect(url_for("admin.dashboard"))


@admin_bp.get("/orders")
@login_required
def orders():
    query = LicenseOrder.query
    status = request.args.get("status", "").strip().upper()
    if status in {"PENDING", "PAID", "APPROVED", "COMPLETED", "REJECTED"}:
        if status in {"APPROVED", "COMPLETED"}:
            query = query.filter(LicenseOrder.status.in_({"APPROVED", "COMPLETED"}))
        else:
            query = query.filter(LicenseOrder.status == status)
    orders = query.order_by(LicenseOrder.created_at.desc()).all()
    return render_template("admin/orders.html", orders=orders, status=status)


@admin_bp.get("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    order = db.session.get(LicenseOrder, order_id)
    if not order:
        return "Order not found", 404
    return render_template("admin/order_detail.html", order=order)


@admin_bp.get("/orders/<int:order_id>/license-key")
@login_required
def get_order_license_key(order_id):
    """Retrieve the full license key for an order (temporary, from session)."""
    order = db.session.get(LicenseOrder, order_id)
    if not order:
        return jsonify({"success": False, "error": "Order not found"}), 404
    if not order.license_id:
        return jsonify({"success": False, "error": "No license for this order"}), 404
    
    full_key = _recall_order_license_key(order_id)
    if not full_key:
        return jsonify({"success": False, "error": "License key not available (may have expired from session)"}), 404
    
    return jsonify({
        "success": True,
        "license_key": full_key,
        "order_id": order.id,
        "customer_email": order.customer_email,
        "plan": order.plan,
        "message": "This is the FULL license key. Keep it secure and deliver only to the customer.",
    })


@admin_bp.post("/orders/<int:order_id>/mark-paid")
@login_required
def mark_order_paid(order_id):
    if not check_csrf():
        flash("Invalid security token.")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    order = db.session.get(LicenseOrder, order_id)
    if not order:
        return "Order not found", 404
    if order.status == "REJECTED":
        flash("Rejected orders cannot be marked as paid.")
        return redirect(url_for("admin.order_detail", order_id=order_id))

    order.payment_status = "PAID"
    order.payment_method = request.form.get("payment_method") or order.payment_method or "Manual Review"
    order.payment_reference = request.form.get("payment_reference") or order.payment_reference
    order.payment_notes = request.form.get("payment_notes") or order.payment_notes
    order.paid_at = utc_now()
    db.session.commit()
    try:
        send_order_notification(order, event="payment_received")
    except Exception:
        pass
    audit("ORDER_MARKED_PAID", order.license_id, metadata={"order_id": order.id, "payment_method": order.payment_method, "payment_reference": order.payment_reference})
    flash("Order payment verified and marked as paid.")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@admin_bp.post("/orders/<int:order_id>/approve")
@login_required
def approve_order(order_id):
    if not check_csrf():
        flash("Invalid security token.")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    order = db.session.get(LicenseOrder, order_id)
    if not order:
        return "Order not found", 404
    if order.status in {"APPROVED", "COMPLETED"}:
        flash("This order has already been completed.")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    if order.status == "REJECTED":
        flash("Rejected orders cannot be approved.")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    if order.payment_status != "PAID":
        flash("Payment must be verified before approving this order.")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    if order.license_id is not None:
        flash("This order already has a generated license.")
        return redirect(url_for("admin.order_detail", order_id=order_id))

    created_license = None
    try:
        key, created_license = create_license(
            plan=order.plan,
            max_devices=order.max_devices or PLAN_MAX_DEVICES.get(order.plan, 1),
            customer_name=order.customer_name,
            customer_email=order.customer_email,
            notes=order.notes,
        )
        # CRITICAL: Verify the generated key is valid and can be found
        try:
            verify_issued_license(key, created_license, plan=order.plan, max_devices=order.max_devices or PLAN_MAX_DEVICES.get(order.plan, 1))
        except Exception as error:
            current_app.logger.error(
                "Order %s license verification failed last4=%s error=%s",
                order.id,
                getattr(created_license, "license_key_last4", "????"),
                error,
            )
            db.session.delete(created_license)
            db.session.commit()
            raise ValueError(f"License verification failed: {error}")

        order.license_id = created_license.id
        order.status = "COMPLETED"
        order.approved_at = utc_now()
        order.completed_at = utc_now()
        db.session.commit()
        # Store full key temporarily in session for admin retrieval
        _remember_order_license_key(order.id, key)
        try:
            send_order_notification(order, event="license_ready", license_key=key)
        except Exception:
            pass
        audit("ORDER_APPROVED", created_license.id, metadata={"order_id": order.id, "plan": order.plan, "license_key_last4": created_license.license_key_last4})
        flash(f"Order approved and license {key} created.")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    except Exception as error:
        db.session.rollback()
        if created_license is not None:
            try:
                db.session.delete(created_license)
                db.session.commit()
            except Exception:
                db.session.rollback()
        flash(f"Unable to approve order: {error}")
        return redirect(url_for("admin.order_detail", order_id=order_id))


@admin_bp.post("/orders/<int:order_id>/send-license-email")
@login_required
def send_order_license_email(order_id):
    current_app.logger.info("License email requested for order #%s", order_id)

    if not check_csrf():
        current_app.logger.warning("License email rejected for order #%s: invalid CSRF token", order_id)
        flash("Invalid security token.")
        return redirect(url_for("admin.order_detail", order_id=order_id))

    order = db.session.get(LicenseOrder, order_id)
    if not order:
        current_app.logger.error("License email failed for order #%s: order not found", order_id)
        return "Order not found", 404
    if not order.license_id:
        current_app.logger.error("License email failed for order #%s: missing license", order_id)
        flash("This order does not have a license yet.")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    if not order.customer_email:
        current_app.logger.error("License email failed for order #%s: customer email missing", order_id)
        flash("This order has no customer email to send the license to.")
        return redirect(url_for("admin.order_detail", order_id=order_id))

    current_app.logger.info("Customer email found for order #%s: %s", order_id, order.customer_email)

    full_key = _recall_order_license_key(order_id)
    if not full_key:
        current_app.logger.error("License email failed for order #%s: full license key missing from session", order_id)
        flash("The full license key is not available for this order. Please retrieve it first.")
        return redirect(url_for("admin.order_detail", order_id=order_id))

    current_app.logger.info("License key found for order #%s", order_id)

    try:
        sent, message = send_license_email(order, license_key=full_key)
    except Exception as error:
        current_app.logger.exception("Unexpected exception while sending license email for order #%s", order_id)
        flash(f"Failed to send license email: {error}")
        return redirect(url_for("admin.order_detail", order_id=order_id))

    if not sent:
        current_app.logger.error("License email not sent for order #%s: %s", order_id, message)
        flash(f"Failed to send license email: {message}")
        return redirect(url_for("admin.order_detail", order_id=order_id))

    current_app.logger.info("License email sent successfully for order #%s to %s", order_id, order.customer_email)
    flash(f"License email sent successfully to {order.customer_email}.")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@admin_bp.post("/orders/<int:order_id>/reject")
@login_required
def reject_order(order_id):
    if not check_csrf():
        flash("Invalid security token.")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    order = db.session.get(LicenseOrder, order_id)
    if not order:
        return "Order not found", 404
    if order.status != "PENDING":
        flash("Only pending orders can be rejected.")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    order.status = "REJECTED"
    order.approved_at = None
    if order.payment_status == "UNPAID":
        order.payment_status = "FAILED"
    db.session.commit()
    audit("ORDER_REJECTED", order.license_id, metadata={"order_id": order.id, "plan": order.plan})
    flash("Order rejected.")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@admin_bp.get("/licenses")
@login_required
def licenses():
    query = License.query
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip().upper()
    plan = request.args.get("plan", "").strip().upper()
    if search:
        query = query.filter((License.customer_name.ilike(f"%{search}%")) | (License.customer_email.ilike(f"%{search}%")))
    if status:
        query = query.filter_by(status=status)
    if plan:
        query = query.filter_by(plan=plan)
    records = query.order_by(License.created_at.desc()).all()
    counts = dict(
        db.session.query(LicenseDevice.license_id, func.count(LicenseDevice.id))
        .filter(LicenseDevice.status == "ACTIVE")
        .group_by(LicenseDevice.license_id)
        .all()
    )
    for record in records:
        record.active_devices = counts.get(record.id, 0)
    return render_template("admin/licenses.html", licenses=records, q=search, status=status, plan=plan)


@admin_bp.route("/licenses/create", methods=["GET", "POST"])
@login_required
def create_license_page():
    if request.method == "POST":
        if not check_csrf():
            flash("Invalid security token.")
            return redirect(url_for("admin.create_license_page"))
        try:
            expires = request.form.get("expires_at") or None
            expires_at = datetime.fromisoformat(expires) if expires else None
            key, record = create_license(
                plan=request.form.get("plan", "MONTHLY"),
                max_devices=request.form.get("max_devices", 1),
                expires_at=expires_at,
                customer_name=request.form.get("customer_name"),
                customer_email=request.form.get("customer_email"),
                notes=request.form.get("notes"),
            )
            audit("LICENSE_CREATED", record.id)
            return render_template("admin/license_created.html", license_key=key, license=record)
        except (TypeError, ValueError) as error:
            flash(str(error))
    return render_template("admin/create_license.html")


@admin_bp.get("/licenses/<int:license_id>")
@login_required
def license_detail(license_id):
    record = db.session.get(License, license_id)
    if not record:
        return "License not found", 404
    devices = LicenseDevice.query.filter_by(license_id=record.id).order_by(LicenseDevice.activated_at.desc()).all()
    return render_template("admin/license_detail.html", license=record, devices=devices)


@admin_bp.post("/licenses/<int:license_id>/action")
@login_required
def license_action(license_id):
    if not check_csrf():
        flash("Invalid security token.")
        return redirect(url_for("admin.license_detail", license_id=license_id))
    record = db.session.get(License, license_id)
    action = request.form.get("action")
    if not record:
        return "License not found", 404
    if action == "revoke":
        record.status = "REVOKED"
        audit("LICENSE_REVOKED", record.id)
    elif action == "reactivate":
        if record.expires_at and record.expires_at <= utc_now():
            flash("Expired licenses cannot be reactivated.")
            return redirect(url_for("admin.license_detail", license_id=license_id))
        record.status = "ACTIVE"
        audit("LICENSE_REACTIVATED", record.id)
    elif action == "extend":
        record.expires_at = datetime.fromisoformat(request.form["expires_at"])
        audit("LICENSE_EXTENDED", record.id)
    elif action == "devices":
        record.max_devices = max(1, int(request.form["max_devices"]))
        audit("MAX_DEVICES_CHANGED", record.id)
    elif action == "deactivate_device":
        device = db.session.get(LicenseDevice, int(request.form["device_id"]))
        if device and device.license_id == record.id:
            device.status = "INACTIVE"
            device.deactivated_at = utc_now()
            audit("DEVICE_DEACTIVATED", record.id, device.device_id)
    db.session.commit()
    return redirect(url_for("admin.license_detail", license_id=license_id))


@admin_bp.get("/devices")
@login_required
def devices():
    records = LicenseDevice.query.options(joinedload(LicenseDevice.license)).order_by(LicenseDevice.last_seen_at.desc()).all()
    return render_template("admin/devices.html", devices=records)


@admin_bp.post("/devices/<int:device_id>/deactivate")
@login_required
def device_deactivate(device_id):
    if not check_csrf():
        flash("Invalid security token.")
        return redirect(url_for("admin.devices"))
    device = db.session.get(LicenseDevice, device_id)
    if device:
        device.status = "INACTIVE"
        device.deactivated_at = utc_now()
        audit("DEVICE_DEACTIVATED", device.license_id, device.device_id)
        db.session.commit()
    return redirect(url_for("admin.devices"))


@admin_bp.cli.command("create-admin")
def create_admin_command():
    """Create the first administrator interactively from the terminal."""
    import getpass
    email = input("Admin email: ").strip().lower()
    password = getpass.getpass("Admin password: ")
    if not email or not password:
        raise SystemExit("Email and password are required")
    db.session.add(AdminUser(email=email, password_hash=generate_password_hash(password)))
    db.session.commit()
    print("Admin created")
