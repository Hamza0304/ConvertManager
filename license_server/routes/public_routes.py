from email.utils import parseaddr

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from license_server.models import LicenseOrder, db

public_bp = Blueprint("public", __name__)

PLAN_PRICES = {
    "MONTHLY": 19.99,
    "YEARLY": 99.99,
    "LIFETIME": 249.99,
}

PLAN_DETAILS = {
    "MONTHLY": {"name": "Monthly", "duration": "1 month", "max_devices": 1, "price": 19.99, "features": ["1 device", "Email support", "Monthly updates"]},
    "YEARLY": {"name": "Yearly", "duration": "12 months", "max_devices": 3, "price": 99.99, "features": ["3 devices", "Priority support", "Annual updates"]},
    "LIFETIME": {"name": "Lifetime", "duration": "Unlimited", "max_devices": 5, "price": 249.99, "features": ["5 devices", "Lifetime access", "Premium support"]},
}


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


def _order_form_context(plan, extra=None):
    details = PLAN_DETAILS.get(plan, {})
    context = {
        "plan": plan,
        "plan_name": details.get("name", plan),
        "price": PLAN_PRICES.get(plan, 0),
        "duration": details.get("duration", ""),
        "max_devices": details.get("max_devices", 1),
        "payment_instructions": current_app.config.get("PAYMENT_INSTRUCTIONS", ""),
    }
    if extra:
        context.update(extra)
    return context

@public_bp.get("/plans/")
@public_bp.get("/plans")
def plans():
    return render_template("public/plans.html", plans=PLAN_DETAILS)


@public_bp.get("/order")
def order_form():
    plan = (request.args.get("plan", "MONTHLY") or "MONTHLY").strip().upper()
    if plan not in PLAN_DETAILS:
        flash("Selected plan is invalid.")
        return redirect(url_for("public.plans"))
    return render_template("public/order.html", **_order_form_context(plan))


@public_bp.post("/order")
def order_submit():
    plan = (request.form.get("plan") or "").strip().upper()
    customer_name = (request.form.get("customer_name") or "").strip()
    customer_email = (request.form.get("customer_email") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    requested_max_devices = request.form.get("max_devices")

    if plan not in PLAN_DETAILS:
        flash("Selected plan is invalid.")
        return render_template("public/order.html", **_order_form_context(plan or "MONTHLY", {"error": "Selected plan is invalid."})), 400
    if not customer_name:
        flash("Full name is required.")
        return render_template("public/order.html", **_order_form_context(plan, {"error": "Full name is required."})), 400
    if not customer_email or not _is_valid_email(customer_email):
        flash("A valid email address is required.")
        return render_template("public/order.html", **_order_form_context(plan, {"error": "A valid email address is required."})), 400

    allowed_max_devices = PLAN_DETAILS[plan]["max_devices"]
    try:
        normalized_max_devices = int(requested_max_devices) if requested_max_devices not in {None, ""} else allowed_max_devices
    except (TypeError, ValueError):
        normalized_max_devices = allowed_max_devices
    if normalized_max_devices < 1 or normalized_max_devices > allowed_max_devices:
        normalized_max_devices = allowed_max_devices

    order = LicenseOrder(
        customer_name=customer_name,
        customer_email=customer_email,
        phone=phone,
        plan=plan,
        price=PLAN_PRICES[plan],
        max_devices=normalized_max_devices,
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
    return render_template(
        "public/order_success.html",
        order=order,
        payment=_payment_settings(),
        plan_name=PLAN_DETAILS.get(order.plan, {}).get("name", order.plan),
    )



@public_bp.get("/")
def home():
    return render_template(
        "public/home.html",
        version="1.0.0",
        download_url=current_app.config.get(
            "CONVERTMANAGER_DOWNLOAD_URL",
            "#"
        ),
        plans_url=current_app.config.get(
            "CONVERTMANAGER_PLANS_URL",
            "/plans"
        )
    )