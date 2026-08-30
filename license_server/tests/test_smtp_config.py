"""Runtime SMTP configuration used by the Admin Dashboard email path."""

from unittest.mock import patch

import pytest
from werkzeug.security import generate_password_hash

from license_server.app import create_app
from license_server.config import Config, ENV_FILE, apply_smtp_config, load_package_env
from license_server.models import AdminUser, LicenseOrder, db, utc_now
from license_server.services.email_service import (
    _smtp_settings,
    send_email,
    smtp_runtime_diagnostics,
)
from license_server.services.license_service import create_license


class SmtpTestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-secret-key"


@pytest.fixture
def app():
    app = create_app(SmtpTestConfig)
    with app.app_context():
        db.create_all()
        admin = AdminUser(
            email="admin@test.local",
            password_hash=generate_password_hash("admin123"),
            is_active=True,
        )
        db.session.add(admin)
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def admin_session(app):
    client = app.test_client()
    with client.session_transaction() as session:
        csrf = session.get("csrf_token")
        if not csrf:
            import secrets
            csrf = secrets.token_urlsafe(32)
            session["csrf_token"] = csrf
    client.post(
        "/admin/login",
        data={
            "email": "admin@test.local",
            "password": "admin123",
            "csrf_token": csrf,
        },
        follow_redirects=True,
    )
    return client


def test_package_env_file_is_in_license_server_directory():
    assert ENV_FILE.name == ".env"
    assert ENV_FILE.parent.name == "license_server"
    assert ENV_FILE.is_file(), f"Expected SMTP .env at {ENV_FILE}"


def test_flask_app_config_loads_smtp_from_package_env():
    load_package_env()
    app = create_app(Config)

    assert app.config["SMTP_HOST"] == "smtp.gmail.com"
    assert int(app.config["SMTP_PORT"]) == 587
    assert app.config["SMTP_USERNAME"]
    assert app.config["SMTP_FROM_EMAIL"]
    assert app.config["SMTP_FROM_NAME"] == "ConvertManager"
    assert app.config["SMTP_USE_TLS"] is True
    assert app.config["SMTP_USE_SSL"] is False
    if app.config["SMTP_USERNAME"]:
        assert app.config["SMTP_PASSWORD"], "SMTP_PASSWORD must be set when username is configured"


def test_smtp_settings_match_app_config_in_same_runtime():
    app = create_app(Config)
    apply_smtp_config(app)

    with app.app_context():
        settings = _smtp_settings()
        assert app.config["SMTP_HOST"] == "smtp.gmail.com"
        assert settings["host"] == "smtp.gmail.com"
        assert settings["host"] == app.config["SMTP_HOST"]
        assert settings["port"] == int(app.config["SMTP_PORT"])
        assert settings["username"] == app.config["SMTP_USERNAME"]
        assert settings["from_email"] == app.config["SMTP_FROM_EMAIL"]
        assert bool(settings["password"]) == bool(app.config.get("SMTP_PASSWORD"))

        diagnostics = smtp_runtime_diagnostics()
        assert diagnostics["SMTP_HOST"] == "configured"
        assert diagnostics["SMTP_PORT"] == 587
        assert diagnostics["SMTP_USERNAME"] == "configured"
        assert diagnostics["SMTP_PASSWORD"] == "configured"
        assert diagnostics["SMTP_FROM_EMAIL"] == "configured"
        assert diagnostics["SMTP_USE_TLS"] == "true"
        assert diagnostics["SMTP_USE_SSL"] == "false"
        assert diagnostics["runtime_host"] == "smtp.gmail.com"
        assert diagnostics["app_config_host"] == "smtp.gmail.com"


def test_admin_smtp_status_endpoint_matches_runtime(app, admin_session):
    apply_smtp_config(app)
    with app.app_context():
        assert app.config["SMTP_HOST"] == "smtp.gmail.com"
        assert _smtp_settings()["host"] == "smtp.gmail.com"

    response = admin_session.get("/admin/smtp-status")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["runtime_host"] == "smtp.gmail.com"
    assert payload["app_config_host"] == "smtp.gmail.com"
    assert payload["SMTP_PASSWORD"] == "configured"
    with app.app_context():
        assert payload["SMTP_PASSWORD"] != app.config.get("SMTP_PASSWORD")


def test_send_email_uses_gmail_settings_from_app_config():
    app = create_app(Config)
    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            captured["host"] = host
            captured["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def ehlo(self):
            return None

        def starttls(self):
            captured["starttls"] = True

        def login(self, username, password):
            captured["username"] = username
            captured["password_configured"] = bool(password)

        def send_message(self, message):
            captured["sent_to"] = message["To"]

    with app.app_context():
        assert app.config["SMTP_HOST"] == "smtp.gmail.com"
        assert _smtp_settings()["host"] == "smtp.gmail.com"
        with patch("license_server.services.email_service.smtplib.SMTP", FakeSMTP):
            success, error = send_email(
                "Your ConvertManager license key",
                "customer@example.com",
                "License key body",
            )

    assert success is True
    assert error is None
    assert captured["host"] == "smtp.gmail.com"
    assert captured["port"] == 587
    assert captured["starttls"] is True
    assert captured["username"] == app.config["SMTP_USERNAME"]
    assert captured["password_configured"] is True
    assert captured["sent_to"] == "customer@example.com"


def test_send_license_email_route_reaches_smtp(app, admin_session, monkeypatch):
    apply_smtp_config(app)
    smtp_calls = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            smtp_calls["host"] = host
            smtp_calls["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def ehlo(self):
            return None

        def starttls(self):
            smtp_calls["tls"] = True

        def login(self, username, password):
            smtp_calls["login"] = True
            smtp_calls["username"] = username

        def send_message(self, message):
            smtp_calls["recipient"] = message["To"]
            smtp_calls["body"] = message.get_content()

    with app.app_context():
        assert app.config["SMTP_HOST"] == "smtp.gmail.com"
        assert _smtp_settings()["host"] == "smtp.gmail.com"
        order = LicenseOrder(
            customer_name="SMTP User",
            customer_email="smtp.user@example.com",
            phone="123456",
            plan="MONTHLY",
            price=19.99,
            max_devices=1,
            status="PENDING",
            payment_status="PAID",
            payment_method="Manual Review",
        )
        db.session.add(order)
        db.session.commit()
        order_id = order.id
        key, created_license = create_license(
            plan=order.plan,
            max_devices=1,
            customer_name=order.customer_name,
            customer_email=order.customer_email,
            notes=order.notes,
        )
        order.license_id = created_license.id
        order.status = "COMPLETED"
        order.approved_at = utc_now()
        order.completed_at = utc_now()
        db.session.commit()

    with admin_session.session_transaction() as session:
        csrf = session.get("csrf_token")
        session["order_license_keys"] = {str(order_id): key}

    monkeypatch.setattr("license_server.services.email_service.smtplib.SMTP", FakeSMTP)

    response = admin_session.post(
        f"/admin/orders/{order_id}/send-license-email",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )

    assert response.status_code in [200, 302]
    assert smtp_calls["host"] == "smtp.gmail.com"
    assert smtp_calls["port"] == 587
    assert smtp_calls["tls"] is True
    assert smtp_calls["login"] is True
    assert smtp_calls["recipient"] == "smtp.user@example.com"
    assert key in smtp_calls["body"]
    assert "password" not in smtp_calls
