import re
from datetime import timedelta

import pytest
from werkzeug.security import generate_password_hash

from license_server.app import create_app
from license_server.config import Config
from license_server.models import AdminUser, FreeAccessGrant, FreeAccessSetting, License, LicenseDevice, LicenseOrder, Plan, db, utc_now
from license_server.services.license_service import create_license
from license_server.services.free_access_service import register_or_refresh


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "plan-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    LICENSE_ADMIN_TOKEN = "test-admin"


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.session.add(AdminUser(email="admin@example.com", password_hash=generate_password_hash("password")))
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def login(client):
    page = client.get("/admin/login")
    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', page.get_data(as_text=True)).group(1)
    response = client.post("/admin/login", data={"email": "admin@example.com", "password": "password", "csrf_token": token})
    assert response.status_code == 302
    with client.session_transaction() as session:
        return session["csrf_token"]


def test_public_plans_and_orders_use_database_values(app, client):
    with app.app_context():
        monthly = Plan.query.filter_by(code="MONTHLY").one()
        monthly.price = 14.99
        monthly.max_devices = 5
        monthly.duration_days = 60
        db.session.commit()

    page = client.get("/plans")
    assert b"14.99" in page.data
    assert b"5" in page.data
    assert b"60 days" in page.data

    response = client.post("/order", data={
        "plan": "MONTHLY", "customer_name": "Database User", "customer_email": "db@example.com",
    })
    assert response.status_code == 302
    with app.app_context():
        order = LicenseOrder.query.filter_by(customer_email="db@example.com").one()
        assert order.price == 14.99
        assert order.max_devices == 5
        assert order.duration_days == 60


def test_admin_can_edit_and_deactivate_plan(app, client):
    token = login(client)
    with app.app_context():
        plan_id = Plan.query.filter_by(code="MONTHLY").one().id

    response = client.post(f"/admin/plans/{plan_id}/edit", data={
        "csrf_token": token, "code": "MONTHLY", "name": "Monthly Updated", "type": "PERSONAL",
        "price": "12.50", "max_devices": "4", "duration_days": "45", "features": "Priority support\nFast updates",
    })
    assert response.status_code == 302
    with app.app_context():
        plan = db.session.get(Plan, plan_id)
        assert plan.name == "Monthly Updated"
        assert plan.price == 12.5
        assert plan.max_devices == 4
        assert plan.duration_days == 45
        assert plan.feature_list() == ["Priority support", "Fast updates"]

    response = client.post(f"/admin/plans/{plan_id}/toggle", data={"csrf_token": token})
    assert response.status_code == 302
    assert b"Monthly Updated" not in client.get("/plans").data


def test_free_access_extension_is_applied_once(app):
    with app.app_context():
        settings = FreeAccessSetting.query.first()
        settings.duration_days = 30
        started = utc_now() - timedelta(days=1)
        grant = FreeAccessGrant(device_id="free-device", started_at=started, applied_duration_days=30, expires_at=started + timedelta(days=30))
        db.session.add(grant)
        db.session.commit()
        settings.duration_days = 45
        db.session.commit()

        first_settings, first = register_or_refresh("free-device")
        first_expiration = first.expires_at
        assert first_settings.duration_days == 45
        assert first.applied_duration_days == 45
        assert first_expiration == started + timedelta(days=45)

        _, second = register_or_refresh("free-device")
        assert second.expires_at == first_expiration


def test_plans_api_reflects_each_database_price_change(app, client):
    with app.app_context():
        plan = Plan.query.filter_by(code="MONTHLY").one()
        plan.price = 10.99
        db.session.commit()
    assert client.get("/api/license/plans").get_json()["plans"][0]["price"] == 10.99
    with app.app_context():
        Plan.query.filter_by(code="MONTHLY").one().price = 8.99
        db.session.commit()
    assert client.get("/api/license/plans").get_json()["plans"][0]["price"] == 8.99


def test_admin_reset_requires_auth_confirmation_and_preserves_configuration(app, client):
    assert client.get("/admin/testing/reset").status_code == 302
    with app.app_context():
        key, license_record = create_license("MONTHLY", 1)
        order = LicenseOrder(customer_name="Reset", customer_email="reset@example.com", plan="MONTHLY", price=1, max_devices=1)
        db.session.add(order)
        db.session.flush()
        device = LicenseDevice(license_id=license_record.id, device_id="reset-device")
        db.session.add(device)
        db.session.commit()
        plan_count = Plan.query.count()
        settings_id = FreeAccessSetting.query.first().id

    token = login(client)
    assert client.get("/admin/testing/reset").status_code == 200
    wrong = client.post("/admin/testing/reset", data={"csrf_token": token, "confirmation": "no"})
    assert wrong.status_code == 200
    with app.app_context():
        assert License.query.count() == 1
        assert LicenseOrder.query.count() == 1

    reset = client.post("/admin/testing/reset", data={"csrf_token": token, "confirmation": "RESET"})
    assert reset.status_code == 200
    with app.app_context():
        assert License.query.count() == 0
        assert LicenseOrder.query.count() == 0
        assert LicenseDevice.query.count() == 0
        assert Plan.query.count() == plan_count
        assert FreeAccessSetting.query.first().id == settings_id
        assert AdminUser.query.count() == 1

    assert client.get("/admin/testing/reset").status_code == 200
