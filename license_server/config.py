import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from sqlalchemy.engine.url import make_url


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"


def load_package_env():
    """Load license_server/.env even when the process started in another directory.

    Empty process-environment values do not block values from the package .env.
    """
    load_dotenv(ENV_FILE, override=False, encoding="utf-8-sig")
    if ENV_FILE.is_file():
        for key, value in dotenv_values(ENV_FILE, encoding="utf-8-sig").items():
            if not key or value is None:
                continue
            current = os.environ.get(key)
            if current is None or str(current).strip() == "":
                os.environ[key] = value
    return ENV_FILE


def _env_bool(name, default):
    raw = os.environ.get(name, default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def smtp_settings_from_env():
    """Read SMTP settings from the process environment after loading .env."""
    load_package_env()
    try:
        port = int(os.environ.get("SMTP_PORT", "587") or "587")
    except (TypeError, ValueError):
        port = 587
    return {
        "SMTP_HOST": os.environ.get("SMTP_HOST", "").strip(),
        "SMTP_PORT": port,
        "SMTP_USERNAME": os.environ.get("SMTP_USERNAME", "").strip(),
        "SMTP_PASSWORD": os.environ.get("SMTP_PASSWORD", ""),
        "SMTP_FROM_EMAIL": os.environ.get("SMTP_FROM_EMAIL", "").strip(),
        "SMTP_FROM_NAME": (os.environ.get("SMTP_FROM_NAME", "ConvertManager") or "ConvertManager").strip(),
        "SMTP_USE_TLS": _env_bool("SMTP_USE_TLS", "true"),
        "SMTP_USE_SSL": _env_bool("SMTP_USE_SSL", "false"),
    }


def apply_smtp_config(app):
    """Force Flask app.config SMTP keys from the package .env / process env."""
    app.config.update(smtp_settings_from_env())


load_package_env()


def resolve_database_uri(uri=None):
    """Build the SQLAlchemy URI and pin relative SQLite files to this package."""
    if uri is None:
        uri = os.environ.get("DATABASE_URL")
    if not uri:
        uri = "mysql+pymysql://{user}:{password}@{host}:{port}/{name}".format(
            user=os.environ.get("DB_USER", "license_user"),
            password=os.environ.get("DB_PASSWORD", ""),
            host=os.environ.get("DB_HOST", "127.0.0.1"),
            port=os.environ.get("DB_PORT", "3306"),
            name=os.environ.get("DB_NAME", "license_server"),
        )
    if uri.startswith("sqlite:///"):
        rest = uri[len("sqlite:///"):]
        if rest and not rest.startswith(":memory:"):
            path = Path(rest)
            if not path.is_absolute():
                path = (BASE_DIR / path).resolve()
            uri = "sqlite:///" + path.as_posix()
    return uri


def describe_database_uri(uri):
    """Return host/database identity for diagnostics. Never include credentials."""
    parsed = make_url(uri)
    return {
        "driver": parsed.drivername,
        "host": parsed.host,
        "port": parsed.port,
        "database": parsed.database,
    }


def sqlalchemy_engine_options(uri):
    if uri.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {
        "pool_size": int(os.environ.get("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "10")),
        "pool_timeout": int(os.environ.get("DB_POOL_TIMEOUT", "30")),
        "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE", "1800")),
    }


class Config:
    # Loaded from license_server/.env (or the process environment). Do not generate
    # a random key at import time — that would invalidate sessions on every restart.
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-change-me"
    SQLALCHEMY_DATABASE_URI = resolve_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = sqlalchemy_engine_options(SQLALCHEMY_DATABASE_URI)
    LICENSE_ADMIN_TOKEN = os.environ.get("LICENSE_ADMIN_TOKEN", "")
    RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
    RATE_LIMIT_MAX_REQUESTS = int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", "30"))
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    # false for local HTTP; set SESSION_COOKIE_SECURE=true behind HTTPS in production.
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax") or "Lax"
    MAX_CONTENT_LENGTH = 16 * 1024

    # Manual bank payment details. Never put real RIB values in source control.
    PAYMENT_ACCOUNT_HOLDER = os.environ.get("PAYMENT_ACCOUNT_HOLDER", "")
    PAYMENT_RIB = os.environ.get("PAYMENT_RIB", "")
    PAYMENT_BANK_NAME = os.environ.get("PAYMENT_BANK_NAME", "")
    PAYMENT_INSTRUCTIONS = os.environ.get(
        "PAYMENT_INSTRUCTIONS",
        "Please use your Order Number as the transfer reference.",
    )
    CONVERTMANAGER_PLANS_URL = os.environ.get("CONVERTMANAGER_PLANS_URL", "http://127.0.0.1:5000/plans")
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    try:
        SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or "587")
    except (TypeError, ValueError):
        SMTP_PORT = 587
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", "")
    SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "ConvertManager")
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
    SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "false").lower() == "true"
