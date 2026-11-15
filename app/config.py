"""Application settings, read from environment variables (or a local .env file)."""

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        instance = BASE_DIR / "instance"
        instance.mkdir(exist_ok=True)
        return f"sqlite:///{instance / 'shop.db'}"
    # Render/Neon/Heroku give "postgres://..." URLs; SQLAlchemy needs the psycopg driver name.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _secret_key() -> str:
    key = os.environ.get("SECRET_KEY", "").strip()
    if key:
        return key
    # Development fallback: keep one random key in instance/ so sessions survive restarts.
    path = BASE_DIR / "instance" / "secret_key"
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip()


def load_config() -> dict:
    bakong_token = os.environ.get("BAKONG_TOKEN", "").strip()
    return {
        "SECRET_KEY": _secret_key(),
        "SQLALCHEMY_DATABASE_URI": _database_url(),
        "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True},
        "MAX_CONTENT_LENGTH": 5 * 1024 * 1024,  # uploads up to 5 MB
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": os.environ.get("SESSION_COOKIE_SECURE", "").lower() in ("1", "true"),
        "CSRF_ENABLED": True,
        "SHOP_NAME": os.environ.get("SHOP_NAME", "Setec Shop"),
        "ADMIN_USERNAME": os.environ.get("ADMIN_USERNAME", "admin"),
        "ADMIN_PASSWORD": os.environ.get("ADMIN_PASSWORD", "admin123"),
        # KHQR / Bakong
        "BAKONG_ACCOUNT_ID": os.environ.get("BAKONG_ACCOUNT_ID", "yourname@aclb"),
        # Needed for banks that share one Bakong ID (ABA: abaakhppxxx@abaa + your account number).
        "BAKONG_ACCOUNT_INFO": os.environ.get("BAKONG_ACCOUNT_INFO", "").strip(),
        "BAKONG_ACQUIRING_BANK": os.environ.get("BAKONG_ACQUIRING_BANK", "").strip(),
        # Your bank's own static KHQR string. When set, it replaces the three settings above.
        "BAKONG_KHQR_TEMPLATE": os.environ.get("BAKONG_KHQR_TEMPLATE", "").strip(),
        "MERCHANT_NAME": os.environ.get("MERCHANT_NAME", os.environ.get("SHOP_NAME", "Setec Shop")),
        "MERCHANT_CITY": os.environ.get("MERCHANT_CITY", "Phnom Penh"),
        "BAKONG_TOKEN": bakong_token,
        "BAKONG_API_URL": os.environ.get("BAKONG_API_URL", "https://api-bakong.nbc.gov.kh/v1").rstrip("/"),
        "PAYMENT_MODE": "bakong" if bakong_token else "demo",
        "PAYMENT_TIMEOUT_MINUTES": int(os.environ.get("PAYMENT_TIMEOUT_MINUTES", "15")),
        "CURRENCY": "USD",
        "PRODUCTS_PER_PAGE": 12,
    }
