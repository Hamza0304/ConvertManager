from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


def ensure_compatible_schema():
    """Add model columns that db.create_all() will not add to existing tables. Never drops data."""
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    for table in db.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_columns:
                continue
            db.session.execute(text(
                f"ALTER TABLE {table.name} ADD COLUMN {column.name} {_column_add_ddl(column)}"
            ))
    db.session.commit()


def _column_add_ddl(column):
    type_sql = column.type.compile(dialect=db.engine.dialect)
    default_sql = None
    if column.default is not None and getattr(column.default, "is_scalar", False):
        value = column.default.arg
        if isinstance(value, bool):
            default_sql = "1" if value else "0"
        elif isinstance(value, (int, float)):
            default_sql = str(value)
        elif isinstance(value, str):
            default_sql = "'" + value.replace("'", "''") + "'"
    elif not column.nullable:
        compiled = str(type_sql).upper()
        if "INT" in compiled or "BOOL" in compiled:
            default_sql = "0"
        elif "CHAR" in compiled or "TEXT" in compiled or "CLOB" in compiled:
            default_sql = "''"
        elif "FLOAT" in compiled or "REAL" in compiled or "NUMERIC" in compiled or "DOUBLE" in compiled:
            default_sql = "0"
    parts = [str(type_sql)]
    if not column.nullable:
        parts.append("NOT NULL")
    if default_sql is not None:
        parts.append("DEFAULT " + default_sql)
    return " ".join(parts)


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class License(db.Model):
    __tablename__ = "licenses"

    id = db.Column(db.Integer, primary_key=True)
    license_key_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    license_key_last4 = db.Column(db.String(4), nullable=False)
    plan = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="NOT_ACTIVATED")
    max_devices = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    activated_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    last_validation_at = db.Column(db.DateTime, nullable=True)
    customer_name = db.Column(db.String(255), nullable=True)
    customer_email = db.Column(db.String(255), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    devices = db.relationship(
        "LicenseDevice",
        back_populates="license",
        cascade="all, delete-orphan",
    )
    orders = db.relationship(
        "LicenseOrder",
        back_populates="license",
        cascade="all, delete-orphan",
    )

    @property
    def key_masked(self):
        return f"****-****-****-{self.license_key_last4}"


class LicenseOrder(db.Model):
    __tablename__ = "license_orders"

    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(255), nullable=False)
    customer_email = db.Column(db.String(255), nullable=False, index=True)
    phone = db.Column(db.String(50), nullable=True)
    plan = db.Column(db.String(20), nullable=False, index=True)
    price = db.Column(db.Float, nullable=False, default=0.0)
    max_devices = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(20), nullable=False, default="PENDING", index=True)
    payment_status = db.Column(db.String(20), nullable=False, default="UNPAID", index=True)
    payment_method = db.Column(db.String(80), nullable=True)
    payment_reference = db.Column(db.String(120), nullable=True)
    payment_notes = db.Column(db.Text, nullable=True)
    payment_instructions = db.Column(db.Text, nullable=True)
    license_id = db.Column(db.Integer, db.ForeignKey("licenses.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    approved_at = db.Column(db.DateTime, nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    license = db.relationship("License", back_populates="orders")


class LicenseDevice(db.Model):
    __tablename__ = "license_devices"

    id = db.Column(db.Integer, primary_key=True)
    license_id = db.Column(db.Integer, db.ForeignKey("licenses.id"), nullable=False, index=True)
    device_id = db.Column(db.String(128), nullable=False)
    activated_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    last_seen_at = db.Column(db.DateTime, nullable=True)
    deactivated_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="ACTIVE")

    license = db.relationship("License", back_populates="devices")
    __table_args__ = (
        db.UniqueConstraint("license_id", "device_id", name="uq_license_device"),
    )

    @property
    def device_id_masked(self):
        if len(self.device_id) <= 10:
            return self.device_id
        return f"{self.device_id[:6]}...{self.device_id[-4:]}"

    @property
    def active(self):
        return self.status == "ACTIVE"

    @property
    def last_seen(self):
        return self.last_seen_at


class AdminUser(db.Model):
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    last_login_at = db.Column(db.DateTime, nullable=True)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey("admin_users.id"), nullable=True)
    action = db.Column(db.String(80), nullable=False)
    license_id = db.Column(db.Integer, db.ForeignKey("licenses.id"), nullable=True)
    device_id = db.Column(db.String(128), nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    metadata_json = db.Column(db.Text, nullable=True)
