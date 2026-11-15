"""Customer pages: home, product details, cart, checkout with KHQR, order confirmation."""

import re
import secrets

from flask import (
    Blueprint, abort, current_app, flash, jsonify, make_response, redirect, render_template,
    request, session, url_for,
)
from sqlalchemy import func, or_, select

from .. import cart, khqr, payments
from ..models import Category, Order, OrderItem, Product, db, utcnow

bp = Blueprint("shop", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[0-9 ()\-]{8,20}$")


def _safe_next(default: str) -> str:
    target = request.form.get("next") or request.args.get("next") or ""
    return target if target.startswith("/") and not target.startswith("//") else default


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _active_product_or_404(product_id: int) -> Product:
    product = db.session.get(Product, product_id)
    if not product or not product.is_active:
        abort(404)
    return product


# ---------------------------------------------------------------- catalog

def _active_products():
    return select(Product).where(Product.status == Product.STATUS_ACTIVE)


def _best_sellers(limit: int) -> list[Product]:
    """Active products ranked by quantity sold in paid orders; unsold ones follow, newest first."""
    sold = (
        select(OrderItem.product_id, func.sum(OrderItem.quantity).label("qty"))
        .join(Order).where(Order.status == Order.STATUS_PAID, OrderItem.product_id.isnot(None))
        .group_by(OrderItem.product_id).subquery()
    )
    query = (
        _active_products().outerjoin(sold, sold.c.product_id == Product.id)
        .order_by(func.coalesce(sold.c.qty, 0).desc(), Product.created_at.desc(), Product.id.desc())
        .limit(limit)
    )
    return list(db.session.execute(query).scalars())


def _category_tiles() -> list[dict]:
    """Categories that have active products, each with a cover picture taken from one of them."""
    tiles = []
    for category in Category.query.order_by(Category.name).all():
        products = [p for p in category.products if p.is_active]
        if products:
            cover = next((p for p in products if p.has_image), products[0])
            tiles.append({"category": category, "count": len(products), "cover": cover})
    return tiles


@bp.get("/")
def home():
    best = _best_sellers(8)
    on_sale = next((p for p in best if p.on_sale), None) or db.session.execute(
        _active_products().where(Product.compare_price > Product.price).limit(1)
    ).scalar()
    return render_template(
        "shop/home.html",
        best_sellers=best,
        hero_product=best[0] if best else None,
        deal_product=on_sale,
        categories=_category_tiles(),
    )


SORTS = {
    "newest": (Product.created_at.desc(), Product.id.desc()),
    "price_asc": (Product.price.asc(), Product.id),
    "price_desc": (Product.price.desc(), Product.id),
    "name": (Product.name.asc(),),
}


@bp.get("/shop")
def shop():
    q = request.args.get("q", "").strip()
    category_id = request.args.get("category", type=int)
    deals = request.args.get("deals") == "1"
    sort = request.args.get("sort", "newest")
    if sort not in SORTS:
        sort = "newest"

    query = _active_products()
    if q:
        like = f"%{q}%"
        query = query.where(or_(Product.name.ilike(like), Product.description.ilike(like)))
    category = db.session.get(Category, category_id) if category_id else None
    if category:
        query = query.where(Product.category_id == category.id)
    if deals:
        query = query.where(Product.compare_price > Product.price)
    page = db.paginate(
        query.order_by(*SORTS[sort]),
        page=request.args.get("page", 1, type=int),
        per_page=current_app.config["PRODUCTS_PER_PAGE"],
        error_out=False,
    )
    filters = {k: v for k, v in {"q": q, "category": category.id if category else None,
                                 "deals": "1" if deals else None, "sort": sort}.items() if v}
    return render_template("shop/shop.html", page=page, q=q, category=category, deals=deals,
                           sort=sort, filters=filters, categories=Category.query.order_by(Category.name).all())


@bp.get("/products/<int:product_id>")
def product_detail(product_id):
    product = _active_product_or_404(product_id)
    share_url = url_for("shop.product_detail", product_id=product.id, _external=True)
    related = []
    if product.category_id:
        related = list(db.session.execute(
            _active_products().where(Product.category_id == product.category_id, Product.id != product.id)
            .order_by(Product.created_at.desc()).limit(4)
        ).scalars())
    return render_template(
        "shop/product.html", product=product, share_url=share_url,
        in_cart=cart.quantity_of(product.id), related=related,
    )


@bp.get("/products/<int:product_id>/image")
def product_image(product_id):
    product = db.session.get(Product, product_id)
    if not product or not product.has_image:
        abort(404)
    response = make_response(product.image_data)
    response.headers["Content-Type"] = product.image_mime
    # The URL carries ?v=<version>, so a new upload gets a new URL and old copies can be cached forever.
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# ---------------------------------------------------------------- cart

@bp.post("/cart/add")
def cart_add():
    product = _active_product_or_404(_int(request.form.get("product_id")))
    wanted = max(1, _int(request.form.get("quantity"), 1))
    back = _safe_next(url_for("shop.product_detail", product_id=product.id))

    if not product.in_stock:
        flash(f"Sorry, {product.name} is out of stock.", "error")
        return redirect(back)
    current = cart.quantity_of(product.id)
    new_total = min(current + wanted, product.stock, cart.MAX_QUANTITY_PER_ITEM)
    cart.set_quantity(product.id, new_total)
    if new_total < current + wanted:
        flash(f"Only {product.stock} of {product.name} in stock — your cart now has {new_total}.", "warning")
    else:
        flash(f"Added {wanted} × {product.name} to your cart.", "success")
    return redirect(back)


@bp.get("/cart")
def cart_view():
    lines = cart.lines()
    return render_template("shop/cart.html", lines=lines, total=cart.total(lines))


@bp.post("/cart/update")
def cart_update():
    product = db.session.get(Product, _int(request.form.get("product_id")))
    if product:
        quantity = max(0, _int(request.form.get("quantity"), 1))
        if quantity > product.stock:
            quantity = product.stock
            flash(f"Only {product.stock} of {product.name} in stock.", "warning")
        cart.set_quantity(product.id, quantity)
        if quantity == 0:
            flash(f"Removed {product.name} from your cart.", "success")
    return redirect(url_for("shop.cart_view"))


@bp.post("/cart/remove")
def cart_remove():
    product_id = _int(request.form.get("product_id"))
    cart.remove(product_id)
    flash("Item removed from your cart.", "success")
    return redirect(url_for("shop.cart_view"))


# ---------------------------------------------------------------- checkout

def _validate_customer(form) -> tuple[dict, dict]:
    data = {
        "customer_name": form.get("customer_name", "").strip(),
        "email": form.get("email", "").strip().lower(),
        "phone": form.get("phone", "").strip(),
        "shipping_address": form.get("shipping_address", "").strip(),
    }
    errors = {}
    if len(data["customer_name"]) < 2:
        errors["customer_name"] = "Please enter your full name."
    elif len(data["customer_name"]) > 120:
        errors["customer_name"] = "Name is too long."
    if not EMAIL_RE.match(data["email"]) or len(data["email"]) > 254:
        errors["email"] = "Please enter a valid email address."
    digits = re.sub(r"\D", "", data["phone"])
    if not PHONE_RE.match(data["phone"]) or not 8 <= len(digits) <= 15:
        errors["phone"] = "Please enter a valid phone number, e.g. 012 345 678."
    if len(data["shipping_address"]) < 8:
        errors["shipping_address"] = "Please enter your full shipping address."
    elif len(data["shipping_address"]) > 500:
        errors["shipping_address"] = "Address is too long."
    return data, errors


def _cancel_previous_pending_order() -> None:
    """A new checkout replaces an unpaid one from the same visitor, so its stock isn't held twice."""
    token = session.pop("pending_order", None)
    if token:
        order = Order.query.filter_by(token=token).first()
        if order and order.is_pending:
            payments.release(order, Order.STATUS_CANCELLED)
            db.session.commit()


@bp.route("/checkout", methods=["GET", "POST"])
def checkout():
    lines = cart.lines()
    if not lines:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("shop.cart_view"))

    form, errors = {}, {}
    if request.method == "POST":
        form, errors = _validate_customer(request.form)
        if not errors:
            _cancel_previous_pending_order()
            payments.expire_stale_orders()
            order, stock_errors = _place_order(form, lines)
            if order:
                session["pending_order"] = order.token
                return redirect(url_for("shop.payment", token=order.token))
            for message in stock_errors:
                flash(message, "error")
            return redirect(url_for("shop.cart_view"))

    return render_template("shop/checkout.html", lines=lines, total=cart.total(lines), form=form, errors=errors)


def _place_order(form: dict, lines: list) -> tuple[Order | None, list[str]]:
    """Create the order and reserve stock in one transaction. Returns (order, []) or (None, errors)."""
    ids = sorted(line.product.id for line in lines)
    # Lock the product rows (PostgreSQL) so two buyers can't take the last item at the same time.
    locked = {
        p.id: p for p in db.session.execute(
            select(Product).where(Product.id.in_(ids)).order_by(Product.id)
            .with_for_update().execution_options(populate_existing=True)  # re-read fresh stock
        ).scalars()
    }
    order = Order(token=secrets.token_urlsafe(24), currency=current_app.config["CURRENCY"], total=0, **form)
    stock_errors, total = [], 0
    for line in lines:
        product = locked.get(line.product.id)
        if not product or not product.is_active:
            stock_errors.append(f"{line.product.name} is no longer available.")
            continue
        if line.quantity > product.stock:
            stock_errors.append(
                f"Only {product.stock} of {product.name} left in stock. Please update your cart."
                if product.stock else f"{product.name} just sold out. Please remove it from your cart."
            )
            continue
        product.stock -= line.quantity
        order.items.append(OrderItem(
            product_id=product.id, product_name=product.name,
            unit_price=product.price, quantity=line.quantity,
        ))
        total += product.price * line.quantity

    if stock_errors:
        db.session.rollback()
        return None, stock_errors

    order.total = total
    db.session.add(order)
    db.session.flush()  # assigns order.id, which the KHQR bill number uses
    payments.attach_khqr(order)
    db.session.commit()
    return order, []


# ---------------------------------------------------------------- payment & confirmation

def _order_or_404(token: str) -> Order:
    order = Order.query.filter_by(token=token).first()
    if not order:
        abort(404)
    return order


def _finish_paid_order(order: Order) -> None:
    if session.get("pending_order") == order.token:
        session.pop("pending_order", None)
        cart.clear()


@bp.get("/orders/<token>/pay")
def payment(token):
    order = _order_or_404(token)
    warning = payments.refresh_status(order)
    if order.is_paid:
        return redirect(url_for("shop.confirmation", token=order.token))
    seconds_left = max(0, int((order.expires_at - utcnow()).total_seconds())) if order.is_pending else 0
    return render_template(
        "shop/payment.html", order=order, warning=warning, seconds_left=seconds_left,
        qr_image=khqr.qr_svg_data_uri(order.khqr) if order.is_pending else None,
    )


@bp.get("/orders/<token>/status")
def payment_status(token):
    order = _order_or_404(token)
    warning = payments.refresh_status(order)
    body = {"status": order.status, "warning": warning}
    if order.is_paid:
        body["redirect"] = url_for("shop.confirmation", token=order.token)
    return jsonify(body)


@bp.post("/orders/<token>/simulate-payment")
def simulate_payment(token):
    if current_app.config["PAYMENT_MODE"] != "demo":
        abort(404)
    order = _order_or_404(token)
    payments.refresh_status(order)
    if not order.is_pending:
        flash("This order can no longer be paid.", "error")
        return redirect(url_for("shop.payment", token=order.token))
    payments.mark_paid(order, "demo")
    db.session.commit()
    return redirect(url_for("shop.confirmation", token=order.token))


@bp.post("/orders/<token>/cancel")
def cancel_order(token):
    order = _order_or_404(token)
    if order.is_pending:
        payments.release(order, Order.STATUS_CANCELLED)
        db.session.commit()
        session.pop("pending_order", None)
        flash("Order cancelled. Your cart is still here.", "success")
    return redirect(url_for("shop.cart_view"))


@bp.get("/orders/<token>")
def confirmation(token):
    order = _order_or_404(token)
    if order.is_pending:
        return redirect(url_for("shop.payment", token=order.token))
    if order.is_paid:
        _finish_paid_order(order)
    return render_template("shop/confirmation.html", order=order)
