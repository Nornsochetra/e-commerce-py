import io

from app.models import Order, OrderItem, Product, db

from .conftest import csrf, first_product, login_admin
from .test_shop import add_to_cart, checkout

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_admin_pages_require_login(client):
    for url in ("/admin/products", "/admin/products/new", "/admin/orders"):
        response = client.get(url)
        assert response.status_code == 302 and "/admin/login" in response.headers["Location"]


def test_wrong_password(client):
    assert "Wrong username or password" in login_admin(client, "nope").get_data(as_text=True)


def test_product_list(client):
    login_admin(client)
    html = client.get("/admin/products").get_data(as_text=True)
    assert "Kampot Pepper Gift Box" in html and "Active" in html and "Add new product" in html


def test_create_product_with_image(app, client):
    login_admin(client)
    token = csrf(client, "/admin/products/new")
    response = client.post("/admin/products/new", content_type="multipart/form-data", data={
        "csrf_token": token, "name": "Angkor Beer Glass", "description": "A glass.",
        "price": "3.50", "stock": "10", "status": "active", "image": (io.BytesIO(PNG), "glass.png"),
    })
    assert response.status_code == 302
    with app.app_context():
        product = Product.query.filter_by(name="Angkor Beer Glass").one()
        assert str(product.price) == "3.50" and product.stock == 10
        assert product.image_mime == "image/png"
        product_id = product.id
    assert client.get(f"/products/{product_id}/image").data == PNG


def test_create_product_validation(app, client):
    login_admin(client)
    token = csrf(client, "/admin/products/new")
    response = client.post("/admin/products/new", content_type="multipart/form-data", data={
        "csrf_token": token, "name": "", "price": "-1", "stock": "abc", "status": "active",
        "image": (io.BytesIO(b"<svg onload=alert(1)>"), "x.svg"),
    })
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "Name is required" in html and "price greater than 0" in html
    assert "whole number" in html and "JPG, PNG, WEBP, GIF or AVIF" in html and "Not saved" in html
    assert "choose your image again" in html


def test_edit_product(app, client):
    login_admin(client)
    product = first_product(app)
    token = csrf(client, f"/admin/products/{product.id}/edit")
    client.post(f"/admin/products/{product.id}/edit", data={
        "csrf_token": token, "name": "Renamed", "description": "New text",
        "price": "1.99", "stock": "3", "status": "inactive",
    })
    with app.app_context():
        updated = db.session.get(Product, product.id)
        assert (updated.name, str(updated.price), updated.stock, updated.status) == ("Renamed", "1.99", 3, "inactive")
        assert updated.has_image  # image kept when no new file is uploaded


def test_delete_product_keeps_order_history(app, client):
    product = first_product(app)
    add_to_cart(client, product.id)
    checkout(client)
    login_admin(client)
    token = csrf(client, "/admin/products")
    client.post(f"/admin/products/{product.id}/delete", data={"csrf_token": token})
    with app.app_context():
        assert db.session.get(Product, product.id) is None
        item = OrderItem.query.one()
        assert item.product_id is None and item.product_name == product.name


def test_order_history_and_details(app, client):
    product = first_product(app)
    add_to_cart(client, product.id, 2)
    checkout(client)
    with app.app_context():
        order = Order.query.one()
        order_id, number = order.id, order.number
    login_admin(client)

    html = client.get("/admin/orders").get_data(as_text=True)
    assert number in html and "Sok Dara" in html and "012 345 678" in html

    assert number in client.get(f"/admin/orders?q={number}").get_data(as_text=True)
    assert "No orders found" in client.get("/admin/orders?q=nobody").get_data(as_text=True)

    html = client.get(f"/admin/orders/{order_id}").get_data(as_text=True)
    assert product.name in html and "Street 271" in html and "Mark as paid" in html


def test_admin_mark_paid(app, client):
    add_to_cart(client, first_product(app).id)
    checkout(client)
    with app.app_context():
        order_id = Order.query.one().id
    login_admin(client)
    token = csrf(client, f"/admin/orders/{order_id}")
    client.post(f"/admin/orders/{order_id}/mark-paid", data={"csrf_token": token})
    with app.app_context():
        order = db.session.get(Order, order_id)
        assert order.status == "paid" and order.payment_ref == "admin:admin"


def test_logout(client):
    login_admin(client)
    token = csrf(client, "/admin/products")
    client.post("/admin/logout", data={"csrf_token": token})
    assert client.get("/admin/products").status_code == 302


def test_dashboard(app, client):
    product = first_product(app)
    add_to_cart(client, product.id, 2)
    checkout(client)
    with app.app_context():
        order = Order.query.one()
        token, number = order.token, order.number
    client.post(f"/orders/{token}/simulate-payment", data={"csrf_token": csrf(client, f"/orders/{token}/pay")})
    login_admin(client)
    response = client.get("/admin/")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Total sales" in html and f"${product.price * 2:,.2f}" in html
    assert number in html and product.name in html and "Sales by category" in html
    assert "data-line-chart" in html
    for days in (7, 90):
        assert client.get(f"/admin/?days={days}").status_code == 200


def test_category_crud(app, client):
    from app.models import Category

    login_admin(client)
    token = csrf(client, "/admin/categories/new")
    client.post("/admin/categories/new", data={"csrf_token": token, "name": "Beauty"})
    response = client.post("/admin/categories/new", data={"csrf_token": token, "name": "beauty"})
    assert "already exists" in response.get_data(as_text=True)
    with app.app_context():
        category_id = Category.query.filter_by(name="Beauty").one().id
    client.post(f"/admin/categories/{category_id}/edit", data={"csrf_token": token, "name": "Beauty & Care"})
    assert "Beauty &amp; Care" in client.get("/admin/categories").get_data(as_text=True)

    product = first_product(app)
    with app.app_context():
        db.session.get(Product, product.id).category_id = category_id
        db.session.commit()
    client.post(f"/admin/categories/{category_id}/delete", data={"csrf_token": token})
    with app.app_context():
        assert db.session.get(Category, category_id) is None
        assert db.session.get(Product, product.id).category_id is None


def test_product_form_category_and_discount(app, client):
    from app.models import Category

    login_admin(client)
    with app.app_context():
        category_id = Category.query.filter_by(name="Fashion").one().id
    token = csrf(client, "/admin/products/new")
    base = {"csrf_token": token, "name": "Silk Scarf", "description": "", "stock": "5", "status": "active",
            "category_id": str(category_id)}
    response = client.post("/admin/products/new", data={**base, "price": "20", "compare_price": "15"})
    assert response.status_code == 400 and "must be higher" in response.get_data(as_text=True)
    client.post("/admin/products/new", data={**base, "price": "20", "compare_price": "25"})
    with app.app_context():
        product = Product.query.filter_by(name="Silk Scarf").one()
        assert product.category_id == category_id and product.discount_percent == 20


def test_customers_page(app, client):
    product = first_product(app)
    for _ in range(2):
        add_to_cart(client, product.id)
        checkout(client)
        with app.app_context():
            token = Order.query.filter_by(status="pending").one().token
        client.post(f"/orders/{token}/simulate-payment", data={"csrf_token": csrf(client, f"/orders/{token}/pay")},
                    follow_redirects=True)  # the confirmation page empties the cart
    with app.app_context():
        spent = sum(o.total for o in Order.query.filter_by(status="paid"))
    assert spent == product.price * 2
    login_admin(client)
    html = client.get("/admin/customers").get_data(as_text=True)
    assert "Sok Dara" in html and "dara@example.com" in html
    assert f"${spent:,.2f}" in html
    assert "No customers match" in client.get("/admin/customers?q=zzz").get_data(as_text=True)


def test_upgrade_adds_new_columns_to_old_database(tmp_path):
    """A database created before categories existed gets the new columns on start."""
    import sqlite3

    from app import create_app, init_database

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, description TEXT NOT NULL, "
                "price NUMERIC(10,2) NOT NULL, stock INTEGER NOT NULL, status VARCHAR(10) NOT NULL, image_data BLOB, "
                "image_mime VARCHAR(50), image_version INTEGER NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)")
    con.execute("INSERT INTO products VALUES (1, 'Mondulkiri Wild Honey', 'x', 9.75, 3, 'active', NULL, NULL, 0, "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')")
    con.commit()
    con.close()
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{path}", "SECRET_KEY": "t"})
    init_database(app)
    with app.app_context():
        product = db.session.get(Product, 1)
        assert product.category.name == "Pantry"


def test_admin_password_follows_environment(tmp_path):
    """Changing ADMIN_PASSWORD (e.g. on Render) and restarting updates the login; stray spaces are ignored."""
    from app import create_app, init_database
    from app.models import AdminUser

    uri = f"sqlite:///{tmp_path / 'pw.db'}"
    for password in ("first-pass", "  new-pass\n"):
        app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": uri, "SECRET_KEY": "t"})
        app.config["ADMIN_PASSWORD"] = password.strip()  # what load_config produces
        init_database(app, seed=False)
    with app.app_context():
        admin = AdminUser.query.one()
        assert admin.check_password("new-pass") and not admin.check_password("first-pass")
