import json
import re
import unittest
from datetime import timedelta

from license_server.app import create_app
from license_server.models import AdminUser, License, LicenseOrder, db, utc_now
from werkzeug.security import generate_password_hash
from license_server.services.license_service import create_license


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LICENSE_ADMIN_TOKEN = "test-admin"
    RATE_LIMIT_WINDOW_SECONDS = 60
    RATE_LIMIT_MAX_REQUESTS = 100
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"


class LicenseServerTests(unittest.TestCase):

    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            self.key, self.record = create_license("MONTHLY", 1, utc_now() + timedelta(days=30))
            self.license_id = self.record.id

    def tearDown(self):
        with self.app.app_context():
            db.drop_all()

    def post(self, endpoint, **payload):
        return self.client.post(
            f"/api/license/{endpoint}",
            json=payload
        )

    def test_activation_validation_info_and_deactivation(self):
        response = self.post("activate", license_key=self.key, device_id="device-a")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["success"])
        self.assertEqual(response.json["license"]["status"], "ACTIVE")

        response = self.post("validate", license_key=self.key, device_id="device-a")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["plan"], "MONTHLY")
        self.assertEqual(response.json["license"]["key"], self.key)
        self.assertEqual(response.json["license"]["status"], "ACTIVE")

        response = self.post("info", license_key=self.key, device_id="device-a")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["active_devices"], 1)

        response = self.post("deactivate", license_key=self.key, device_id="device-a")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["deactivated"])

        response = self.post("validate", license_key=self.key, device_id="device-a")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json["error"], "DEVICE_NOT_AUTHORIZED")

    def test_device_limit_and_invalid_license(self):
        self.assertEqual(self.post("activate", license_key=self.key, device_id="device-a").status_code, 200)
        response = self.post("activate", license_key=self.key, device_id="device-b")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["error"], "DEVICE_LIMIT_REACHED")
        response = self.post("activate", license_key="AAAA-BBBB-CCCC-DDDD", device_id="device-a")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json["error"], "INVALID_LICENSE")

    def test_missing_parameters_and_admin_auth(self):
        response = self.post("activate", license_key=self.key)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["error"], "INVALID_REQUEST")
        response = self.client.post("/api/license/admin/licenses", json={})
        self.assertEqual(response.status_code, 401)
        response = self.client.post(
            "/api/license/admin/licenses",
            json={"plan": "YEARLY", "max_devices": 2},
            headers={"X-Admin-Token": "test-admin"}
        )
        self.assertEqual(response.status_code, 201)

    def test_rate_limit(self):
        self.app.config["RATE_LIMIT_MAX_REQUESTS"] = 1
        self.post("activate", license_key="bad", device_id="device-a")
        response = self.post("activate", license_key="bad", device_id="device-a")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json["error"], "RATE_LIMITED")

    def test_admin_created_license_and_api_device_share_the_dashboard_database(self):
        with self.app.app_context():
            db.session.add(AdminUser(email="admin@example.com", password_hash=generate_password_hash("password")))
            db.session.commit()

        login_page = self.client.get("/admin/login")
        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.get_data(as_text=True)).group(1)
        response = self.client.post("/admin/login", data={
            "email": "admin@example.com", "password": "password", "csrf_token": token,
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        create_page = self.client.get("/admin/licenses/create")
        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', create_page.get_data(as_text=True)).group(1)
        created = self.client.post("/admin/licenses/create", data={
            "csrf_token": token,
            "plan": "MONTHLY",
            "max_devices": "1",
            "customer_name": "Dashboard flow",
            "customer_email": "flow@example.com",
            "notes": "integration test",
        })
        key = re.search(r'data-key="([A-Z0-9-]+)"', created.get_data(as_text=True)).group(1)
        self.assertEqual(self.post("activate", license_key=key, device_id="desktop-a").status_code, 200)
        with self.app.app_context():
            license_id = License.query.filter_by(customer_email="flow@example.com").one().id
        dashboard = self.client.get("/admin/")
        detail = self.client.get(f"/admin/licenses/{license_id}")
        self.assertIn(b"1", dashboard.data)
        self.assertIn(b"desktop-a", detail.data)

    def test_admin_login_redirect_session_and_failures(self):
        with self.app.app_context():
            db.session.add(AdminUser(email="admin@example.com", password_hash=generate_password_hash("password")))
            db.session.commit()

        blocked = self.client.get("/admin/dashboard")
        self.assertEqual(blocked.status_code, 302)
        self.assertIn("/admin/login", blocked.headers["Location"])
        self.assertIn("next=/admin/dashboard", blocked.headers["Location"])

        login_page = self.client.get("/admin/login?next=/admin/dashboard")
        self.assertEqual(login_page.status_code, 200)
        html = login_page.get_data(as_text=True)
        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', html).group(1)
        self.assertIn('name="email"', html)
        self.assertIn('name="password"', html)
        self.assertIn('name="next"', html)
        self.assertIn("method=\"post\"", html.lower())

        bad_csrf = self.client.post(
            "/admin/login?next=/admin/dashboard",
            data={
                "email": "admin@example.com",
                "password": "password",
                "csrf_token": "not-the-token",
                "next": "/admin/dashboard",
            },
        )
        self.assertEqual(bad_csrf.status_code, 302)
        self.assertIn("/admin/login", bad_csrf.headers["Location"])
        self.assertIn("next=", bad_csrf.headers["Location"])

        login_page = self.client.get("/admin/login?next=/admin/dashboard")
        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.get_data(as_text=True)).group(1)
        bad_password = self.client.post(
            "/admin/login?next=/admin/dashboard",
            data={
                "email": "admin@example.com",
                "password": "wrong-password",
                "csrf_token": token,
                "next": "/admin/dashboard",
            },
        )
        self.assertEqual(bad_password.status_code, 302)
        failed_page = self.client.get(bad_password.headers["Location"])
        self.assertEqual(failed_page.status_code, 200)
        self.assertIn(b"Invalid email or password", failed_page.data)

        login_page = self.client.get("/admin/login?next=/admin/dashboard")
        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.get_data(as_text=True)).group(1)
        success = self.client.post(
            "/admin/login?next=/admin/dashboard",
            data={
                "email": "admin@example.com",
                "password": "password",
                "csrf_token": token,
                "next": "/admin/dashboard",
            },
        )
        self.assertEqual(success.status_code, 302)
        self.assertIn("/admin/dashboard", success.headers["Location"])
        with self.client.session_transaction() as sess:
            self.assertTrue(sess.get("admin_user_id"))

        alias = self.client.get("/admin/dashboard")
        self.assertEqual(alias.status_code, 302)
        dashboard = self.client.get("/admin/")
        self.assertEqual(dashboard.status_code, 200)
        refresh = self.client.get("/admin/")
        self.assertEqual(refresh.status_code, 200)

        logout = self.client.get("/admin/logout")
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 302)

        login_page = self.client.get("/admin/login")
        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.get_data(as_text=True)).group(1)
        unsafe = self.client.post(
            "/admin/login",
            data={
                "email": "admin@example.com",
                "password": "password",
                "csrf_token": token,
                "next": "https://evil.example/phish",
            },
        )
        self.assertEqual(unsafe.status_code, 302)
        self.assertNotIn("evil.example", unsafe.headers["Location"])

    def test_health_reports_database_target_without_secrets(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json
        self.assertTrue(payload["success"])
        self.assertEqual(payload["database"], "ok")
        target = payload["database_target"]
        self.assertEqual(target["driver"], "sqlite")
        self.assertEqual(target["database"], ":memory:")
        serialized = json.dumps(payload)
        self.assertNotIn("password", serialized)
        self.assertNotIn("test-admin", serialized)

    def test_relative_sqlite_uri_is_anchored_to_the_server_package(self):
        from license_server.config import BASE_DIR, resolve_database_uri

        uri = resolve_database_uri("sqlite:///license_server.dev.db")
        self.assertTrue(uri.startswith("sqlite:///"))
        self.assertIn(BASE_DIR.as_posix(), uri)
        self.assertTrue(uri.endswith("license_server.dev.db"))
        self.assertNotIn("@", uri.split("sqlite:///")[-1])

    def test_public_order_flow_and_admin_approval(self):
        response = self.client.get("/plans")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"MONTHLY", response.data)

        response = self.client.get("/order?plan=MONTHLY")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Selected Plan", response.data)

        response = self.client.post(
            "/order",
            data={
                "customer_name": "Ali",
                "customer_email": "ali@gmail.com",
                "phone": "+966500000000",
                "plan": "MONTHLY",
                "max_devices": "1",
                "notes": "Initial order",
                "csrf_token": "ignored",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Order Submitted Successfully", response.data)

        with self.app.app_context():
            order = LicenseOrder.query.order_by(LicenseOrder.id.desc()).first()
            self.assertIsNotNone(order)
            self.assertEqual(order.customer_name, "Ali")
            self.assertEqual(order.customer_email, "ali@gmail.com")
            self.assertEqual(order.plan, "MONTHLY")
            self.assertEqual(order.max_devices, 1)
            self.assertEqual(order.payment_status, "UNPAID")
            self.assertEqual(order.status, "PENDING")
            self.assertEqual(order.price, 19.99)

        invalid_email = self.client.post(
            "/order",
            data={
                "customer_name": "Bad",
                "customer_email": "not-an-email",
                "plan": "MONTHLY",
                "max_devices": "1",
                "phone": "+966",
                "notes": "bad",
            }
        )
        self.assertEqual(invalid_email.status_code, 400)

        invalid_plan = self.client.post(
            "/order",
            data={
                "customer_name": "Bad",
                "customer_email": "good@example.com",
                "plan": "INVALID",
                "max_devices": "1",
                "phone": "+966",
                "notes": "bad",
            }
        )
        self.assertEqual(invalid_plan.status_code, 400)

        with self.app.app_context():
            db.session.add(AdminUser(email="admin@example.com", password_hash=generate_password_hash("password")))
            db.session.commit()

        login_page = self.client.get("/admin/login")
        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.get_data(as_text=True)).group(1)
        self.client.post(
            "/admin/login",
            data={
                "email": "admin@example.com",
                "password": "password",
                "csrf_token": token,
            },
            follow_redirects=True,
        )

        orders_page = self.client.get("/admin/orders")
        self.assertEqual(orders_page.status_code, 200)
        self.assertIn(b"Ali", orders_page.data)

        with self.app.app_context():
            order = LicenseOrder.query.order_by(LicenseOrder.id.desc()).first()
            detail_page = self.client.get(f"/admin/orders/{order.id}")
            self.assertEqual(detail_page.status_code, 200)
            self.assertIn(b"Ali", detail_page.data)

        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', detail_page.get_data(as_text=True)).group(1)

        paid_response = self.client.post(f"/admin/orders/{order.id}/mark-paid", data={"csrf_token": token, "payment_method": "Bank Transfer", "payment_reference": "REF-123", "payment_notes": "manual verification"})
        self.assertEqual(paid_response.status_code, 302)

        with self.app.app_context():
            order = db.session.get(LicenseOrder, order.id)
            self.assertEqual(order.payment_status, "PAID")
            self.assertIsNotNone(order.paid_at)

        create_response = self.client.post(f"/admin/orders/{order.id}/approve", data={"csrf_token": token})
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            order = db.session.get(LicenseOrder, order.id)
            self.assertEqual(order.status, "COMPLETED")
            self.assertIsNotNone(order.license_id)
            license = db.session.get(License, order.license_id)
            self.assertIsNotNone(license)
            self.assertEqual(license.customer_name, "Ali")
            self.assertEqual(license.customer_email, "ali@gmail.com")
            self.assertEqual(license.plan, "MONTHLY")

        duplicate = self.client.post(f"/admin/orders/{order.id}/approve", data={"csrf_token": token})
        self.assertEqual(duplicate.status_code, 302)

        with self.app.app_context():
            order = db.session.get(LicenseOrder, order.id)
            self.assertEqual(order.status, "COMPLETED")
            self.assertEqual(License.query.filter_by(customer_email="ali@gmail.com").count(), 1)

        rejected = self.client.post(
            "/order",
            data={
                "customer_name": "Reject User",
                "customer_email": "reject@example.com",
                "plan": "YEARLY",
                "max_devices": "2",
                "phone": "+966",
                "notes": "reject me",
            },
            follow_redirects=True,
        )
        self.assertEqual(rejected.status_code, 200)
        with self.app.app_context():
            pending = LicenseOrder.query.filter_by(customer_email="reject@example.com").first()
            self.assertIsNotNone(pending)
            reject_token = re.search(r'name="csrf_token"\s+value="([^"]+)"', self.client.get(f"/admin/orders/{pending.id}").get_data(as_text=True)).group(1)
            reject_response = self.client.post(f"/admin/orders/{pending.id}/reject", data={"csrf_token": reject_token})
            self.assertEqual(reject_response.status_code, 302)
            self.assertEqual(db.session.get(LicenseOrder, pending.id).status, "REJECTED")


if __name__ == "__main__":
    unittest.main()
