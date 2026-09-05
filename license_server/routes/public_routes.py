from email.utils import parseaddr

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from license_server.models import LicenseOrder, Plan, db

public_bp = Blueprint("public", __name__)


@public_bp.context_processor
def inject_public_csrf():
    return {"csrf_token": lambda: ""}


def _is_valid_email(value):
    if not value:
        return False
    return bool(parseaddr(value)[1]) and "@" in value and "." in value


def _payment_settings():
    return {
        "account_holder": (current_app.config.get("PAYMENT_ACCOUNT_HOLDER") or "").strip(),
        "rib": (current_app.config.get("PAYMENT_RIB") or "").strip(),
        "bank_name": (current_app.config.get("PAYMENT_BANK_NAME") or "").strip(),
        "instructions": (current_app.config.get("PAYMENT_INSTRUCTIONS") or "").strip(),
    }


def _duration_label(plan):
    return "Lifetime" if plan.duration_days is None else f"{plan.duration_days} days"


def _order_form_context(code, extra=None):
    selected = Plan.query.filter_by(code=code, active=True).first()
    context = {
        "plan": code,
        "plan_name": selected.name if selected else code,
        "price": selected.price if selected else 0,
        "duration": _duration_label(selected) if selected else "",
        "max_devices": selected.max_devices if selected else 1,
        "payment_instructions": current_app.config.get("PAYMENT_INSTRUCTIONS", ""),
    }
    if extra:
        context.update(extra)
    return context


@public_bp.get("/plans/")
@public_bp.get("/plans")
def plans():
    records = Plan.query.filter_by(active=True).order_by(Plan.price.asc()).all()
    return render_template("public/plans.html", plans=records)


@public_bp.get("/order")
def order_form():
    code = (request.args.get("plan", "MONTHLY") or "MONTHLY").strip().upper()
    if not Plan.query.filter_by(code=code, active=True).first():
        flash("Selected plan is invalid.")
        return redirect(url_for("public.plans"))
    return render_template("public/order.html", **_order_form_context(code))


@public_bp.post("/order")
def order_submit():
    code = (request.form.get("plan") or "").strip().upper()
    customer_name = (request.form.get("customer_name") or "").strip()
    customer_email = (request.form.get("customer_email") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    requested_max_devices = request.form.get("max_devices")
    selected = Plan.query.filter_by(code=code, active=True).first()
    if not selected:
        flash("Selected plan is invalid.")
        return render_template("public/order.html", **_order_form_context(code or "MONTHLY", {"error": "Selected plan is invalid."})), 400
    if not customer_name:
        flash("Full name is required.")
        return render_template("public/order.html", **_order_form_context(code, {"error": "Full name is required."})), 400
    if not customer_email or not _is_valid_email(customer_email):
        flash("A valid email address is required.")
        return render_template("public/order.html", **_order_form_context(code, {"error": "A valid email address is required."})), 400
    try:
        max_devices = int(requested_max_devices) if requested_max_devices not in {None, ""} else selected.max_devices
    except (TypeError, ValueError):
        max_devices = selected.max_devices
    max_devices = max(1, min(max_devices, selected.max_devices))

    order = LicenseOrder(
        customer_name=customer_name,
        customer_email=customer_email,
        phone=phone,
        plan=selected.code,
        plan_id=selected.id,
        duration_days=selected.duration_days,
        price=selected.price,
        max_devices=max_devices,
        status="PENDING",
        payment_status="UNPAID",
        payment_method="Bank Transfer",
        payment_reference=None,
        payment_instructions=current_app.config.get("PAYMENT_INSTRUCTIONS", ""),
        notes=notes,
    )
    db.session.add(order)
    db.session.commit()
    order.payment_reference = f"ORDER-{order.id}"
    db.session.commit()
    return redirect(url_for("public.order_confirmation", order_id=order.id))


@public_bp.get("/order/<int:order_id>/confirmation")
def order_confirmation(order_id):
    order = db.session.get(LicenseOrder, order_id)
    if not order:
        flash("Order was not found.")
        return redirect(url_for("public.plans"))
    plan_name = Plan.query.filter_by(code=order.plan).with_entities(Plan.name).scalar() or order.plan
    return render_template("public/order_success.html", order=order, payment=_payment_settings(), plan_name=plan_name)


@public_bp.get("/")
def home():
    return render_template(
        "public/home.html",
        version="1.0.0",
        download_url=current_app.config.get("CONVERTMANAGER_DOWNLOAD_URL", "#"),
        plans_url=current_app.config.get("CONVERTMANAGER_PLANS_URL", "/plans"),
    )
