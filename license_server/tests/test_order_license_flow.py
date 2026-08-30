"""
Integration test for the complete order → license creation → activation flow.

This test verifies that:
1. Customer submits an order
2. Order appears in admin dashboard
3. Admin marks payment as PAID
4. System creates a valid license
5. License key can be activated through the API
6. Device activation works
"""

import json
import pytest
from flask import Flask

from license_server.app import create_app
from license_server.config import Config
from license_server.models import (
    AdminUser,
    LicenseDevice,
    LicenseOrder,
    db,
    utc_now,
)
from license_server.services.license_service import create_license, find_license, normalize_key, valid_key_format
from werkzeug.security import generate_password_hash


class TestConfig(Config):
    """Configuration for testing with SQLite in-memory database."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-secret-key"
    WTF_CSRF_ENABLED = False


@pytest.fixture
def app():
    """Create and configure a test app."""
    app = create_app(TestConfig)
    
    with app.app_context():
        db.create_all()
        
        # Create a test admin user
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
def client(app):
    """Create a test client."""
    return app.test_client()


@pytest.fixture
def admin_session(client):
    """Login as admin and return client with session."""
    # First, get CSRF token from login page
    response = client.get("/admin/login")
    assert response.status_code == 200
    
    # Extract csrf_token from response (if using Flask-WTF)
    # For now, we'll use the session-based approach
    with client.session_transaction() as session:
        csrf = session.get("csrf_token")
        if not csrf:
            # Generate one manually for testing
            import secrets
            csrf = secrets.token_urlsafe(32)
            session["csrf_token"] = csrf
    
    # Login
    response = client.post(
        "/admin/login",
        data={
            "email": "admin@test.local",
            "password": "admin123",
            "csrf_token": csrf,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    
    return client


def test_complete_order_flow(app, client, admin_session):
    """Test the complete workflow: order → payment → license creation → activation."""
    
    # STEP 1: Customer submits an order for YEARLY plan
    print("\n=== STEP 1: Customer submits order ===")
    order_response = client.post(
        "/order",
        data={
            "plan": "YEARLY",
            "customer_name": "John Doe",
            "customer_email": "john@example.com",
            "phone": "1234567890",
            "notes": "Test order",
            "max_devices": "3",
        },
        follow_redirects=False,
    )
    assert order_response.status_code in [200, 302], f"Order submission failed: {order_response.status_code}"
    
    # Get the order from database
    with app.app_context():
        order = LicenseOrder.query.filter_by(customer_email="john@example.com").first()
        assert order is not None, "Order not found in database"
        assert order.status == "PENDING", f"Order status should be PENDING, got {order.status}"
        assert order.payment_status == "UNPAID", f"Payment status should be UNPAID, got {order.payment_status}"
        assert order.license_id is None, "License should not exist yet"
        order_id = order.id
        print(f"✓ Order created: #{order_id}, Status: {order.status}, Payment: {order.payment_status}")
    
    # STEP 2: Admin marks payment as PAID
    print("\n=== STEP 2: Admin marks payment as PAID ===")
    with admin_session.session_transaction() as session:
        csrf = session.get("csrf_token")
    
    mark_paid_response = admin_session.post(
        f"/admin/orders/{order_id}/mark-paid",
        data={
            "payment_method": "Manual Review",
            "payment_reference": f"ORDER-{order_id}",
            "payment_notes": "Manual verification complete",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert mark_paid_response.status_code in [200, 302], f"Mark paid failed: {mark_paid_response.status_code}"
    
    with app.app_context():
        order = LicenseOrder.query.get(order_id)
        assert order.payment_status == "PAID", f"Payment should be PAID, got {order.payment_status}"
        assert order.license_id is None, "License should not exist yet after marking paid"
        print(f"✓ Order marked as PAID: {order.payment_status}")
    
    # STEP 3: Admin approves order and creates license
    print("\n=== STEP 3: Admin approves order (creates license) ===")
    with admin_session.session_transaction() as session:
        csrf = session.get("csrf_token")
    
    approve_response = admin_session.post(
        f"/admin/orders/{order_id}/approve",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert approve_response.status_code in [200, 302], f"Approve failed: {approve_response.status_code}"
    
    with app.app_context():
        order = LicenseOrder.query.get(order_id)
        assert order.status == "COMPLETED", f"Order status should be COMPLETED, got {order.status}"
        assert order.license_id is not None, "License should be created after approval"
        license_id = order.license_id
        print(f"✓ Order approved, License created: #{license_id}")
    
    # STEP 4: Retrieve the full license key from session
    print("\n=== STEP 4: Retrieve full license key ===")
    key_response = admin_session.get(f"/admin/orders/{order_id}/license-key")
    assert key_response.status_code == 200, f"Key retrieval failed: {key_response.status_code}"
    
    key_data = key_response.get_json()
    assert key_data["success"], "Key retrieval should succeed"
    full_license_key = key_data["license_key"]
    print(f"✓ Full license key retrieved: {full_license_key}")
    
    # STEP 5: Verify the license key format and validity
    print("\n=== STEP 5: Verify license key format ===")
    assert valid_key_format(full_license_key), f"Key format invalid: {full_license_key}"
    print(f"✓ Key format valid: {full_license_key}")
    
    # STEP 6: Verify find_license() can locate it
    print("\n=== STEP 6: Verify license lookup ===")
    with app.app_context():
        found_license = find_license(full_license_key)
        assert found_license is not None, f"License not found for key: {full_license_key}"
        assert found_license.id == license_id, "Found license ID mismatch"
        assert found_license.plan == "YEARLY", f"Plan mismatch: {found_license.plan}"
        assert found_license.max_devices == 3, f"Max devices mismatch: {found_license.max_devices}"
        print(f"✓ License found: ID={found_license.id}, Plan={found_license.plan}, Max Devices={found_license.max_devices}")
    
    # STEP 7: Activate license through API (simulating desktop app)
    print("\n=== STEP 7: Activate license through API ===")
    device_id = "test-device-12345"
    activation_response = client.post(
        "/api/license/activate",
        data=json.dumps({
            "license_key": full_license_key,
            "device_id": device_id,
        }),
        content_type="application/json",
    )
    assert activation_response.status_code == 200, f"Activation failed: {activation_response.status_code}"
    
    activation_data = activation_response.get_json()
    assert activation_data["success"], f"Activation should succeed: {activation_data}"
    assert activation_data["license"]["status"] == "ACTIVE", "License status should be ACTIVE after activation"
    print(f"✓ License activated successfully, Status: {activation_data['license']['status']}")
    
    # STEP 8: Verify device was created and linked
    print("\n=== STEP 8: Verify device creation ===")
    with app.app_context():
        device = LicenseDevice.query.filter_by(
            license_id=license_id,
            device_id=device_id,
        ).first()
        assert device is not None, "Device not found for license"
        assert device.status == "ACTIVE", f"Device status should be ACTIVE, got {device.status}"
        print(f"✓ Device created and linked: {device.device_id}, Status: {device.status}")
    
    # STEP 9: Verify no duplicate license was created
    print("\n=== STEP 9: Verify no duplicate license ===")
    with app.app_context():
        order = LicenseOrder.query.get(order_id)
        assert order.license_id == license_id, "License ID should not change on reactivation"
        license_count = LicenseOrder.query.filter_by(customer_email="john@example.com").count()
        assert license_count == 1, f"Should have exactly 1 order, got {license_count}"
        print(f"✓ No duplicate licenses created")
    
    # STEP 10: Test validation with same device
    print("\n=== STEP 10: Test license validation ===")
    validation_response = client.post(
        "/api/license/validate",
        data=json.dumps({
            "license_key": full_license_key,
            "device_id": device_id,
        }),
        content_type="application/json",
    )
    assert validation_response.status_code == 200, "Validation failed"
    validation_data = validation_response.get_json()
    assert validation_data["success"], "Validation should succeed"
    print(f"✓ License validation successful")
    
    print("\n" + "=" * 50)
    print("✓ ALL TESTS PASSED!")
    print("Complete order → license → activation workflow verified")
    print("=" * 50)


def test_invalid_key_rejection(app, client):
    """Test that invalid keys are properly rejected."""
    print("\n=== Test: Invalid key rejection ===")
    
    response = client.post(
        "/api/license/activate",
        data=json.dumps({
            "license_key": "INVALID-KEY-1234",
            "device_id": "test-device",
        }),
        content_type="application/json",
    )
    
    assert response.status_code == 404, f"Should reject invalid key, got {response.status_code}"
    data = response.get_json()
    assert not data["success"], "Should not succeed with invalid key"
    print(f"✓ Invalid key properly rejected: {data['error']}")


def test_duplicate_click_prevention(app, client, admin_session):
    """Test that clicking 'Approve' twice doesn't create duplicate licenses."""
    print("\n=== Test: Duplicate click prevention ===")
    
    # Create order
    with app.app_context():
        order = LicenseOrder(
            customer_name="Test User",
            customer_email="test@example.com",
            phone="123456",
            plan="YEARLY",
            price=99.99,
            max_devices=3,
            status="PENDING",
            payment_status="PAID",
            payment_method="Manual Review",
        )
        db.session.add(order)
        db.session.commit()
        order_id = order.id
    
    # Get CSRF token
    with admin_session.session_transaction() as session:
        csrf = session.get("csrf_token")
    
    # First approval
    response1 = admin_session.post(
        f"/admin/orders/{order_id}/approve",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert response1.status_code in [200, 302]
    
    with app.app_context():
        order1 = LicenseOrder.query.get(order_id)
        license_id_1 = order1.license_id
        assert license_id_1 is not None, "First approval should create license"
        print(f"✓ First approval created license: #{license_id_1}")
    
    # Second approval (duplicate click)
    response2 = admin_session.post(
        f"/admin/orders/{order_id}/approve",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    # Should be rejected
    assert response2.status_code in [200, 302]
    
    with app.app_context():
        order2 = LicenseOrder.query.get(order_id)
        license_id_2 = order2.license_id
        assert license_id_2 == license_id_1, "Second approval should not create new license"
        
        # Verify only 1 license exists for this customer
        from license_server.models import License
        licenses = License.query.filter_by(customer_email="test@example.com").all()
        assert len(licenses) == 1, f"Should have 1 license, got {len(licenses)}"
        print(f"✓ Duplicate click prevented, same license returned: #{license_id_2}")


def test_send_license_email_route_uses_full_key_and_customer_email(app, admin_session, monkeypatch):
    """Ensure the admin route sends the actual full key to the order's customer email."""
    with app.app_context():
        order = LicenseOrder(
            customer_name="Email User",
            customer_email="email.user@example.com",
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

    captured = {}

    def fake_send_email(subject, recipient, body, html_body=None):
        captured["subject"] = subject
        captured["recipient"] = recipient
        captured["body"] = body
        captured["html_body"] = html_body
        return True, None

    monkeypatch.setattr("license_server.services.email_service.send_email", fake_send_email)

    response = admin_session.post(
        f"/admin/orders/{order_id}/send-license-email",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )

    assert response.status_code in [200, 302], response.get_data(as_text=True)
    assert captured["recipient"] == "email.user@example.com"
    assert key in captured["body"]
    assert "****-****-****-" not in captured["body"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
