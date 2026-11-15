"""Database tables: products, orders, order items and admin users."""

from datetime import datetime, timezone
from decimal import Decimal

from flask import url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import deferred
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def utcnow() -> datetime:
    """Current UTC time without tzinfo (stored the same way in SQLite and PostgreSQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    products = db.relationship("Product", back_populates="category")


class Product(db.Model):
    __tablename__ = "products"

    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUSES = (STATUS_ACTIVE, STATUS_INACTIVE)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    price = db.Column(db.Numeric(10, 2), nullable=False)
    # Optional "was" price: when higher than price, the shop shows a discount badge.
    compare_price = db.Column(db.Numeric(10, 2))
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id", ondelete="SET NULL"), index=True)
    stock = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(10), nullable=False, default=STATUS_ACTIVE)
    # The image is stored in the database so it survives redeploys on hosts with no persistent disk.
    image_data = deferred(db.Column(db.LargeBinary))
    image_mime = db.Column(db.String(50))
    image_version = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    category = db.relationship("Category", back_populates="products")

    @property
    def on_sale(self) -> bool:
        return bool(self.compare_price and self.compare_price > self.price)

    @property
    def discount_percent(self) -> int:
        if not self.on_sale:
            return 0
        return round((1 - self.price / self.compare_price) * 100)

    @property
    def is_active(self) -> bool:
        return self.status == self.STATUS_ACTIVE

    @property
    def in_stock(self) -> bool:
        return self.stock > 0

    @property
    def has_image(self) -> bool:
        return bool(self.image_mime)

    def image_url(self, external: bool = False) -> str:
        if self.has_image:
            return url_for("shop.product_image", product_id=self.id, v=self.image_version, _external=external)
        return url_for("static", filename="img/placeholder.svg", _external=external)


class Order(db.Model):
    __tablename__ = "orders"

    STATUS_PENDING = "pending"  # waiting for KHQR payment
    STATUS_PAID = "paid"
    STATUS_CANCELLED = "cancelled"
    STATUS_EXPIRED = "expired"
    STATUSES = (STATUS_PENDING, STATUS_PAID, STATUS_CANCELLED, STATUS_EXPIRED)

    id = db.Column(db.Integer, primary_key=True)
    # Random, unguessable id used in the customer's URLs (the numeric id is shown, never used to look up).
    token = db.Column(db.String(40), nullable=False, unique=True, index=True)
    customer_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    shipping_address = db.Column(db.Text, nullable=False)
    total = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="USD")
    status = db.Column(db.String(12), nullable=False, default=STATUS_PENDING, index=True)
    # KHQR payment
    khqr = db.Column(db.Text)
    khqr_md5 = db.Column(db.String(32), index=True)
    expires_at = db.Column(db.DateTime)
    last_checked_at = db.Column(db.DateTime)
    paid_at = db.Column(db.DateTime)
    payment_ref = db.Column(db.String(128))  # Bakong transaction hash, or "demo"/"admin"
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    items = db.relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )

    @property
    def number(self) -> str:
        return f"ORD-{self.id:05d}"

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def is_pending(self) -> bool:
        return self.status == self.STATUS_PENDING

    @property
    def is_paid(self) -> bool:
        return self.status == self.STATUS_PAID


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    # Keep the order line when a product is deleted later: name and price are copied here.
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="SET NULL"))
    product_name = db.Column(db.String(120), nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

    order = db.relationship("Order", back_populates="items")
    product = db.relationship("Product")

    @property
    def subtotal(self) -> Decimal:
        return self.unit_price * self.quantity


class AdminUser(db.Model):
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False, unique=True)
    password_hash = db.Column(db.String(256), nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)
