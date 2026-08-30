import logging
import os
import smtplib
from email.message import EmailMessage

from flask import current_app, has_app_context


logger = logging.getLogger(__name__)

_SMTP_TRUE = {"1", "true", "yes", "on"}


def _config_map():
    if has_app_context():
        return current_app.config
    return {}


def _text_setting(key, default=""):
    candidates = []
    app_config = _config_map()
    if key in app_config:
        candidates.append(app_config.get(key))
    candidates.append(os.environ.get(key))
    for value in candidates:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _password_setting():
    candidates = []
    app_config = _config_map()
    if "SMTP_PASSWORD" in app_config:
        candidates.append(app_config.get("SMTP_PASSWORD"))
    candidates.append(os.environ.get("SMTP_PASSWORD"))
    for value in candidates:
        if value is None:
            continue
        password = str(value).strip().replace(" ", "").replace("\t", "").replace("\n", "")
        if password:
            return password
    return ""


def _port_setting():
    candidates = []
    app_config = _config_map()
    if "SMTP_PORT" in app_config:
        candidates.append(app_config.get("SMTP_PORT"))
    candidates.append(os.environ.get("SMTP_PORT"))
    for value in candidates:
        if value is None or value == "":
            continue
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            continue
    return 587


def _bool_setting(key, default=False):
    app_config = _config_map()
    if key in app_config:
        value = app_config.get(key)
        if isinstance(value, bool):
            return value
        if value is not None and str(value).strip() != "":
            return str(value).strip().lower() in _SMTP_TRUE
    env_value = os.environ.get(key)
    if env_value is not None and str(env_value).strip() != "":
        return str(env_value).strip().lower() in _SMTP_TRUE
    return default


def _smtp_settings():
    username = _text_setting("SMTP_USERNAME")
    from_email = _text_setting("SMTP_FROM_EMAIL")
    password = _password_setting()

    if not from_email and "@" in username:
        from_email = username

    if "@" not in username and "@" in from_email:
        username = from_email

    return {
        "host": _text_setting("SMTP_HOST"),
        "port": _port_setting(),
        "username": username,
        "password": password,
        "use_tls": _bool_setting("SMTP_USE_TLS", True),
        "use_ssl": _bool_setting("SMTP_USE_SSL", False),
        "from_email": from_email,
        "from_name": _text_setting("SMTP_FROM_NAME", "ConvertManager") or "ConvertManager",
    }


def _configured_label(value):
    return "configured" if value else "missing"


def smtp_runtime_diagnostics():
    """Safe SMTP snapshot for logs and admin diagnostics. Never includes secrets."""
    settings = _smtp_settings()
    app_host = ""
    if has_app_context():
        app_host = current_app.config.get("SMTP_HOST") or ""
    return {
        "SMTP_HOST": _configured_label(settings["host"]),
        "SMTP_PORT": settings["port"],
        "SMTP_USERNAME": _configured_label(settings["username"]),
        "SMTP_PASSWORD": _configured_label(settings["password"]),
        "SMTP_FROM_EMAIL": _configured_label(settings["from_email"]),
        "SMTP_USE_TLS": str(settings["use_tls"]).lower(),
        "SMTP_USE_SSL": str(settings["use_ssl"]).lower(),
        "runtime_host": settings["host"] or "missing",
        "app_config_host": str(app_host).strip() or "missing",
    }


def is_email_configured():
    settings = _smtp_settings()

    return (
        bool(settings["host"])
        and bool(settings["from_email"])
        and bool(settings["username"])
        and bool(settings["password"])
    )


def _safe_smtp_error(error):
    """
    Convert SMTP exceptions into safe messages.

    Never include passwords or sensitive SMTP credentials.
    """

    if isinstance(error, smtplib.SMTPAuthenticationError):
        return (
            "SMTP authentication failed. "
            "Check your Gmail address and Google App Password."
        )

    if isinstance(error, smtplib.SMTPConnectError):
        return (
            "Unable to connect to the SMTP server. "
            "Check SMTP host and port."
        )

    if isinstance(error, smtplib.SMTPServerDisconnected):
        return (
            "The SMTP server disconnected the connection."
        )

    if isinstance(error, smtplib.SMTPException):
        return (
            f"SMTP error: {error.__class__.__name__}"
        )

    if isinstance(error, TimeoutError):
        return "SMTP connection timed out."

    if isinstance(error, OSError):
        return (
            "Unable to connect to the SMTP server. "
            f"{error.__class__.__name__}"
        )

    return (
        f"Unexpected email error: "
        f"{error.__class__.__name__}"
    )


def send_email(subject, recipient, body, html_body=None):
    """
    Send an email using the configured SMTP server.

    Returns:
        (True, None) on success
        (False, safe_error_message) on failure
    """

    if not recipient:
        logger.warning("Email delivery skipped: recipient is empty.")
        return False, "No recipient email address was provided."

    settings = _smtp_settings()

    if not settings["host"]:
        diagnostics = smtp_runtime_diagnostics()
        logger.error(
            "SMTP configuration error: SMTP_HOST is empty. %s",
            " ".join(f"{key}={value}" for key, value in diagnostics.items()),
        )
        return False, "SMTP host is not configured."

    if not settings["from_email"]:
        logger.error(
            "SMTP configuration error: SMTP_FROM_EMAIL is empty."
        )
        return False, "SMTP sender email is not configured."

    if not settings["username"]:
        logger.error(
            "SMTP configuration error: SMTP_USERNAME is empty."
        )
        return False, "SMTP username is not configured."

    if not settings["password"]:
        logger.error(
            "SMTP configuration error: SMTP_PASSWORD is empty."
        )
        return False, "SMTP password/App Password is not configured."

    message = EmailMessage()

    message["Subject"] = subject
    message["From"] = (
        f"{settings['from_name']} "
        f"<{settings['from_email']}>"
    )
    message["To"] = recipient

    message.set_content(body)

    if html_body:
        message.add_alternative(
            html_body,
            subtype="html"
        )

    logger.info("SMTP email sending started")
    logger.info("SMTP host=%s port=%s", settings["host"], settings["port"])

    try:
        if settings["use_ssl"]:
            if settings["use_tls"]:
                logger.warning(
                    "SMTP configuration has both SSL and TLS enabled. "
                    "Using SSL mode."
                )
            with smtplib.SMTP_SSL(
                settings["host"],
                settings["port"],
                timeout=15,
            ) as server:
                logger.info("SMTP connection established")
                try:
                    server.login(settings["username"], settings["password"])
                except smtplib.SMTPAuthenticationError:
                    logger.error("SMTP authentication failed")
                    raise
                logger.info("SMTP authentication successful")
                server.send_message(message)
        else:
            with smtplib.SMTP(
                settings["host"],
                settings["port"],
                timeout=15,
            ) as server:
                logger.info("SMTP connection established")
                server.ehlo()
                if settings["use_tls"]:
                    server.starttls()
                    server.ehlo()
                    logger.info("SMTP TLS started")
                try:
                    server.login(settings["username"], settings["password"])
                except smtplib.SMTPAuthenticationError:
                    logger.error("SMTP authentication failed")
                    raise
                logger.info("SMTP authentication successful")
                server.send_message(message)

        logger.info("SMTP email sent successfully")
        logger.info("Email sent successfully to %s", recipient)
        return True, None

    except smtplib.SMTPAuthenticationError as error:
        logger.error(
            "SMTP authentication failed username=%s status=%s error=%s",
            settings["username"],
            getattr(error, "smtp_code", None),
            getattr(error, "smtp_error", b"").decode(errors="replace")
            if isinstance(getattr(error, "smtp_error", None), bytes)
            else str(getattr(error, "smtp_error", "")),
        )
        return False, _safe_smtp_error(error)

    except smtplib.SMTPConnectError as error:
        logger.error("SMTP connection failed")
        logger.error(
            "SMTP connection failed host=%s port=%s type=%s error=%s",
            settings["host"],
            settings["port"],
            error.__class__.__name__,
            str(error),
        )
        return False, _safe_smtp_error(error)

    except smtplib.SMTPServerDisconnected as error:
        logger.error("SMTP connection failed")
        logger.error(
            "SMTP server disconnected host=%s port=%s type=%s error=%s",
            settings["host"],
            settings["port"],
            error.__class__.__name__,
            str(error),
        )
        return False, _safe_smtp_error(error)

    except smtplib.SMTPException as error:
        logger.error(
            "SMTPException type=%s error=%s",
            error.__class__.__name__,
            str(error),
        )
        return False, _safe_smtp_error(error)

    except TimeoutError as error:
        logger.error("SMTP connection failed")
        logger.error(
            "SMTP timeout host=%s port=%s type=%s error=%s",
            settings["host"],
            settings["port"],
            error.__class__.__name__,
            str(error),
        )
        return False, _safe_smtp_error(error)

    except OSError as error:
        logger.error("SMTP connection failed")
        logger.error(
            "SMTP network error host=%s port=%s type=%s error=%s",
            settings["host"],
            settings["port"],
            error.__class__.__name__,
            str(error),
        )
        return False, _safe_smtp_error(error)

    except Exception as error:
        logger.exception(
            "Unexpected email delivery error type=%s error=%s",
            error.__class__.__name__,
            str(error),
        )
        return False, _safe_smtp_error(error)


def _license_email_body(order, license_key):
    customer_name = (
        (order.customer_name or "Customer").strip()
        or "Customer"
    )

    plan_name = (
        (order.plan or "MONTHLY").upper()
    )

    license_record = getattr(
        order,
        "license",
        None,
    )

    expires_at = (
        getattr(license_record, "expires_at", None)
        if license_record
        else None
    )

    if expires_at is None:
        expiry_text = "Lifetime"
    else:
        expiry_text = expires_at.strftime(
            "%Y-%m-%d"
        )

    max_devices = (
        getattr(order, "max_devices", None)
        or 1
    )

    lines = [
        f"Hello {customer_name},",
        "",
        "Thank you for your purchase of ConvertManager.",
        "",
        f"Plan: {plan_name}",
        f"License Key: {license_key}",
        f"Maximum Devices: {max_devices}",
        f"Expiry: {expiry_text}",
        "",
        "Activation Instructions:",
        "1. Open ConvertManager.",
        "2. Go to License / Activate License.",
        "3. Enter your license key.",
        "4. Click Activate.",
        "",
        "This is the full license key for your order.",
        "Keep it secure and do not share it publicly.",
        "",
        f"Order ID: {order.id}",
        "",
        "Thank you for choosing ConvertManager.",
    ]

    return "\n".join(lines)


def send_license_email(order, license_key=None):
    logger.info("License email request received for order #%s", getattr(order, "id", None))

    if not order:
        logger.error("License email failed: order not found")
        return False, "Order not found."

    customer_email = (
        getattr(order, "customer_email", None)
        or ""
    ).strip()

    if not customer_email:
        logger.error("License email failed for order #%s: customer email missing", getattr(order, "id", None))
        return False, "No customer email available for this order."

    if not license_key:
        logger.error("License email failed for order #%s: full license key missing", getattr(order, "id", None))
        return False, "No license key available to send."

    logger.info("Customer email found for order #%s: %s", getattr(order, "id", None), customer_email)
    logger.info("License key found for order #%s; preparing SMTP delivery", getattr(order, "id", None))

    subject = "Your ConvertManager license key"

    body = _license_email_body(
        order,
        license_key,
    )

    success, error_message = send_email(
        subject,
        customer_email,
        body,
    )

    if not success:
        logger.error(
            "License email delivery failed "
            "for order_id=%s recipient=%s reason=%s",
            getattr(order, "id", None),
            customer_email,
            error_message,
        )

        return False, error_message

    logger.info(
        "License email delivered successfully "
        "for order_id=%s recipient=%s",
        getattr(order, "id", None),
        customer_email,
    )

    return True, "License email sent successfully."


def send_order_notification(
    order,
    event="payment_received",
    license_key=None,
):
    if not order:
        return False, "Order not found."

    customer_email = (
        getattr(order, "customer_email", None)
        or ""
    ).strip()

    if not customer_email:
        return False, "No customer email available."

    customer_name = (
        getattr(order, "customer_name", None)
        or "Customer"
    )

    if event == "payment_received":

        subject = "ConvertManager payment received"

        body = (
            f"Hi {customer_name},\n\n"
            "We have received your payment for "
            "the ConvertManager order and it is now "
            "awaiting final review.\n\n"
            "Our team will complete the license setup "
            "as soon as possible.\n\n"
            f"Order ID: {order.id}\n"
            f"Plan: {order.plan}\n"
            f"Amount: ${order.price:.2f}\n"
        )

    elif event == "license_ready":

        if not license_key:
            return False, "No license key available."

        subject = "Your ConvertManager license is ready"

        body = (
            f"Hello {customer_name},\n\n"
            "Thank you for your purchase of ConvertManager.\n\n"
            f"Plan:\n{order.plan}\n\n"
            f"Your License Key:\n{license_key}\n\n"
            f"Maximum Devices:\n"
            f"{getattr(order, 'max_devices', None) or 1}\n\n"
            "Activation Instructions:\n"
            "1. Open ConvertManager.\n"
            "2. Go to License / Activate License.\n"
            "3. Enter your license key.\n"
            "4. Click Activate.\n"
        )

    else:

        subject = "ConvertManager order update"

        body = (
            f"Hi {customer_name},\n\n"
            "Your order is being processed.\n\n"
            f"Order ID: {order.id}\n"
        )

    return send_email(
        subject,
        customer_email,
        body,
    )