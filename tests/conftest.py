import re

import pytest

from app import create_app, init_database
from app.models import Product, db


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "SECRET_KEY": "test",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "secret-pass",
        "BAKONG_ACCOUNT_ID": "setec@aclb",
        "BAKONG_KHQR_TEMPLATE": "",
        "BAKONG_TOKEN": "",
        "PAYMENT_MODE": "demo",
    })
    init_database(app)
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client, url="/"):
    """Load a page and return the CSRF token embedded in its forms."""
    html = client.get(url).get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, f"no CSRF token on {url}"
    return match.group(1)


def first_product(app, **filters) -> Product:
    with app.app_context():
        query = Product.query.filter(Product.stock > 0) if not filters else Product.query.filter_by(**filters)
        product = query.order_by(Product.id).first()
        db.session.expunge(product)
        return product


def login_admin(client, password="secret-pass"):
    token = csrf(client, "/admin/login")
    return client.post("/admin/login", data={"username": "admin", "password": password, "csrf_token": token})
