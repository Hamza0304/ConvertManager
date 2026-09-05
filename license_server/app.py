import logging
import os

import click
from flask import Flask, jsonify
from werkzeug.security import generate_password_hash

from license_server.config import Config, apply_smtp_config, describe_database_uri
from license_server.models import AdminUser, db, ensure_compatible_schema
from license_server.routes.license_routes import license_bp
from license_server.routes.admin_routes import admin_bp
from license_server.routes.public_routes import public_bp
from license_server.services.plan_service import ensure_default_plans
from license_server.services.free_access_service import get_settings


def create_app(config_object=None):
    app = Flask(__name__, static_folder="services/static")

    # Load configuration, then re-apply SMTP from license_server/.env so the
    # Admin Dashboard process always sees the same host used by email_service.
    app.config.from_object(config_object or Config)
    apply_smtp_config(app)
    if str(app.config.get("SQLALCHEMY_DATABASE_URI", "")).startswith("sqlite"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            key: value
            for key, value in (app.config.get("SQLALCHEMY_ENGINE_OPTIONS") or {}).items()
            if key in {"connect_args", "echo"}
        }

    # Database
    db.init_app(app)

    # API routes used by the Desktop application
    app.register_blueprint(license_bp)

    # Public order routes
    app.register_blueprint(public_bp)

    # Admin dashboard routes
    app.register_blueprint(admin_bp)

    # Logging
    logging.basicConfig(
        level=app.config.get("LOG_LEVEL", "INFO")
    )

    # Admin dashboard and /api/license share this single SQLAlchemy URI.
    database_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    database_target = describe_database_uri(database_uri)
    if str(database_uri).startswith("sqlite"):
        app.logger.info("License Server SQLite database: %s", database_target.get("database"))
    else:
        app.logger.info(
            "License Server database driver=%s host=%s port=%s database=%s",
            database_target.get("driver"),
            database_target.get("host"),
            database_target.get("port"),
            database_target.get("database"),
        )

    @app.get("/health")
    def health():
        target = describe_database_uri(app.config["SQLALCHEMY_DATABASE_URI"])
        try:
            db.session.execute(db.text("SELECT 1"))
            return jsonify({
                "success": True,
                "status": "ok",
                "database": "ok",
                "database_target": target,
            })
        except Exception:
            return jsonify({
                "success": False,
                "status": "error",
                "database": "error",
                "database_target": target,
            }), 500

    # Temporary database initialization
    # Flask-Migrate will replace this later.
    with app.app_context():
        db.create_all()
        ensure_compatible_schema()
        ensure_default_plans()
        get_settings()
        from license_server.services.email_service import smtp_runtime_diagnostics

        smtp_status = smtp_runtime_diagnostics()
        app.logger.info(
            "SMTP runtime %s",
            " ".join(f"{key}={value}" for key, value in smtp_status.items()),
        )

    @app.cli.command("create-admin")
    @click.option("--email", prompt="Admin email")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin_command(email, password):
        """Create an administrator in the configured license database."""
        email = email.strip().lower()
        if not email or not password:
            raise click.UsageError("Email and password are required.")
        if AdminUser.query.filter_by(email=email).first():
            raise click.UsageError("An administrator with that email already exists.")
        db.session.add(AdminUser(email=email, password_hash=generate_password_hash(password)))
        db.session.commit()
        click.echo("Admin created")

    return app


app = create_app()

# Deployment verification: 2026-08-31


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=True,
    )
