from datetime import timedelta
from unittest.mock import patch

from app.models import Order, Product, db, utcnow

from .conftest import csrf, first_product

CUSTOMER = {
    "customer_name": "Sok Dara",
    "email": "dara@example.com",
    "phone": "012 345 678",
    "shipping_address": "No. 12, Street 271, Phnom Penh",
}


def add_to_cart(client, product_id, quantity=1):
    token = csrf(client)
    return client.post("/cart/add", data={"product_id": product_id, "quantity": quantity, "csrf_token": token})


def checkout(client, **overrides):
    token = csrf(client, "/checkout")
    return client.post("/checkout", data={**CUSTOMER, **overrides, "csrf_token": token})


def test_home_lists_active_products_only(app, client):
    with app.app_context():
        hidden = Product.query.first()
        hidden.status = Product.STATUS_INACTIVE
        hidden_name = hidden.name
        db.session.commit()
    html = client.get("/").get_data(as_text=True)
    assert "View details" in html and "Add to cart" in html
    assert hidden_name not in html


def test_search(client):
    html = client.get("/shop?q=honey").get_data(as_text=True)
    assert "Mondulkiri Wild Honey" in html
    assert "Krama Scarf" not in html


def test_home_sections(client):
    html = client.get("/").get_data(as_text=True)
    assert "Popular categories" in html and "Best selling products" in html
    assert "Scan &amp; Pay" in html and "Pantry" in html
    assert "-17%" in html  # Kampot pepper: $12.50 instead of $15.00


def test_shop_filters_and_sort(app, client):
    from app.models import Category

    with app.app_context():
        pantry = Category.query.filter_by(name="Pantry").one().id
    html = client.get(f"/shop?category={pantry}").get_data(as_text=True)
    assert "Mondulkiri Wild Honey" in html and "Krama Scarf" not in html

    html = client.get("/shop?deals=1").get_data(as_text=True)
    assert "Kampot Pepper Gift Box" in html and "Mondulkiri Wild Honey" not in html

    html = client.get("/shop?sort=price_asc").get_data(as_text=True)
    assert html.index("Palm Sugar Cubes") < html.index("Rattan Market Basket")


def test_best_sellers_rank_by_paid_quantity(app, client):
    honey = first_product(app, name="Mondulkiri Wild Honey")
    add_to_cart(client, honey.id, 3)
    checkout(client)
    with app.app_context():
        token = Order.query.one().token
    client.post(f"/orders/{token}/simulate-payment", data={"csrf_token": csrf(client, f"/orders/{token}/pay")})
    html = client.get("/").get_data(as_text=True)
    section = html[html.index("Best selling products"):]
    assert section.index("Mondulkiri Wild Honey") < section.index("Lotus Scented Candle")


def test_product_detail_has_share_links_and_og_tags(app, client):
    product = first_product(app)
    html = client.get(f"/products/{product.id}").get_data(as_text=True)
    assert "facebook.com/sharer/sharer.php?u=http%3A//localhost/products/" in html
    assert "t.me/share/url?url=" in html
    assert 'property="og:image"' in html


def test_inactive_product_detail_is_404(app, client):
    product = first_product(app)
    with app.app_context():
        db.session.get(Product, product.id).status = Product.STATUS_INACTIVE
        db.session.commit()
    assert client.get(f"/products/{product.id}").status_code == 404


def test_product_image_is_served(app, client):
    product = first_product(app)
    response = client.get(f"/products/{product.id}/image")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/svg+xml"


def test_cart_add_update_remove(app, client):
    product = first_product(app)
    add_to_cart(client, product.id, 2)
    html = client.get("/cart").get_data(as_text=True)
    assert product.name in html
    assert f"${product.price * 2:,.2f}" in html

    token = csrf(client, "/cart")
    client.post("/cart/update", data={"product_id": product.id, "quantity": 3, "csrf_token": token})
    with client.session_transaction() as s:
        assert s["cart"] == {str(product.id): 3}

    client.post("/cart/remove", data={"product_id": product.id, "csrf_token": token})
    assert "Your cart is empty" in client.get("/cart").get_data(as_text=True)


def test_cart_is_capped_at_stock(app, client):
    product = first_product(app)
    add_to_cart(client, product.id, product.stock + 10)
    with client.session_transaction() as s:
        assert s["cart"][str(product.id)] == product.stock


def test_out_of_stock_cannot_be_added(app, client):
    product = first_product(app, stock=0)
    add_to_cart(client, product.id)
    with client.session_transaction() as s:
        assert not s.get("cart")


def test_post_without_csrf_is_rejected(app, client):
    product = first_product(app)
    response = client.post("/cart/add", data={"product_id": product.id})
    assert response.status_code == 400


def test_checkout_validates_form(app, client):
    add_to_cart(client, first_product(app).id)
    response = checkout(client, email="not-an-email", phone="12", customer_name="")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "valid email" in html and "valid phone" in html and "full name" in html
    with app.app_context():
        assert Order.query.count() == 0


def test_full_checkout_flow_with_demo_payment(app, client):
    product = first_product(app)
    add_to_cart(client, product.id, 2)

    response = checkout(client)
    assert response.status_code == 302
    with app.app_context():
        order = Order.query.one()
        token, number = order.token, order.number
        assert order.status == "pending"
        assert order.total == product.price * 2
        assert order.customer_name == "Sok Dara"
        assert order.items[0].quantity == 2
        assert order.khqr.startswith("000201010212") and len(order.khqr_md5) == 32
        assert db.session.get(Product, product.id).stock == product.stock - 2  # reserved
    assert response.headers["Location"].endswith(f"/orders/{token}/pay")

    html = client.get(f"/orders/{token}/pay").get_data(as_text=True)
    assert "KHQR" in html and "data:image/svg+xml" in html and "Simulate successful payment" in html
    assert client.get(f"/orders/{token}/status").get_json()["status"] == "pending"

    pay_token = csrf(client, f"/orders/{token}/pay")
    response = client.post(f"/orders/{token}/simulate-payment", data={"csrf_token": pay_token})
    assert response.headers["Location"].endswith(f"/orders/{token}")

    html = client.get(f"/orders/{token}").get_data(as_text=True)
    assert "Thank you, Sok!" in html and number in html and f"${product.price * 2:,.2f}" in html
    with client.session_transaction() as s:
        assert not s.get("cart")  # cart emptied after payment
    with app.app_context():
        assert Order.query.one().status == "paid"


def test_cancel_restores_stock_and_keeps_cart(app, client):
    product = first_product(app)
    add_to_cart(client, product.id, 1)
    checkout(client)
    with app.app_context():
        token = Order.query.one().token
    pay_token = csrf(client, f"/orders/{token}/pay")
    client.post(f"/orders/{token}/cancel", data={"csrf_token": pay_token})
    with app.app_context():
        assert Order.query.one().status == "cancelled"
        assert db.session.get(Product, product.id).stock == product.stock
    with client.session_transaction() as s:
        assert s["cart"] == {str(product.id): 1}


def test_expired_order_releases_stock(app, client):
    product = first_product(app)
    add_to_cart(client, product.id, 1)
    checkout(client)
    with app.app_context():
        order = Order.query.one()
        order.expires_at = utcnow() - timedelta(seconds=1)
        token = order.token
        db.session.commit()
    assert client.get(f"/orders/{token}/status").get_json()["status"] == "expired"
    with app.app_context():
        assert db.session.get(Product, product.id).stock == product.stock


def test_checkout_again_replaces_unpaid_order(app, client):
    product = first_product(app)
    add_to_cart(client, product.id, 1)
    checkout(client)
    checkout(client)
    with app.app_context():
        statuses = sorted(o.status for o in Order.query.all())
        assert statuses == ["cancelled", "pending"]
        assert db.session.get(Product, product.id).stock == product.stock - 1


def test_checkout_fails_when_stock_ran_out(app, client):
    product = first_product(app)
    add_to_cart(client, product.id, 2)
    with app.app_context():
        db.session.get(Product, product.id).stock = 1
        db.session.commit()
    response = checkout(client)
    assert response.headers["Location"].endswith("/cart")
    with app.app_context():
        assert Order.query.count() == 0
        assert db.session.get(Product, product.id).stock == 1


def test_bakong_mode_marks_order_paid(app, client):
    app.config.update(PAYMENT_MODE="bakong", BAKONG_TOKEN="token")
    add_to_cart(client, first_product(app).id)
    checkout(client)
    with app.app_context():
        token = Order.query.one().token

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"responseCode": 0, "data": {"hash": "abc123", "toAccountId": "setec@aclb", "amount": 1}}

    with patch("app.payments.requests.post", return_value=FakeResponse()) as post:
        body = client.get(f"/orders/{token}/status").get_json()
    assert body["status"] == "paid" and body["redirect"].endswith(f"/orders/{token}")
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer token"}
    with app.app_context():
        assert Order.query.one().payment_ref == "abc123"
    # The demo button must not exist in real Bakong mode.
    assert client.post(f"/orders/{token}/simulate-payment", data={"csrf_token": csrf(client)}).status_code == 404


def test_bakong_unreachable_keeps_order_pending(app, client):
    import requests

    app.config.update(PAYMENT_MODE="bakong", BAKONG_TOKEN="token")
    add_to_cart(client, first_product(app).id)
    checkout(client)
    with app.app_context():
        token = Order.query.one().token
    with patch("app.payments.requests.post", side_effect=requests.ConnectionError("blocked")):
        body = client.get(f"/orders/{token}/status").get_json()
    assert body["status"] == "pending" and "couldn't reach Bakong" in body["warning"]


def test_unknown_order_is_404(client):
    assert client.get("/orders/does-not-exist").status_code == 404
