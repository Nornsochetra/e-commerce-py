"""Admin area: sign in, dashboard, products, categories, orders, customers."""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func, or_, select

from .. import CAMBODIA_OFFSET, payments
from ..models import AdminUser, Category, Order, OrderItem, Product, db, utcnow
from ..security import admin_required

bp = Blueprint("admin", __name__, url_prefix="/admin")

IMAGE_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}
RANGES = {7: "Last 7 days", 30: "Last 30 days", 90: "Last 90 days"}


def _detect_image_type(data: bytes) -> str | None:
    """Trust the file's first bytes, not its name or the browser's claimed type."""
    for signature, mime in IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return "image/avif"
    return None


@bp.app_context_processor
def admin_globals():
    if not request.path.startswith("/admin") or not session.get("admin_id"):
        return {}
    pending = db.session.scalar(select(func.count(Order.id)).where(Order.status == Order.STATUS_PENDING))
    return {"pending_orders": pending}


# ---------------------------------------------------------------- auth

@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_id"):
        return redirect(url_for("admin.dashboard"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        admin = AdminUser.query.filter_by(username=username).first()
        if admin and admin.check_password(request.form.get("password", "")):
            session["admin_id"] = admin.id
            session["admin_name"] = admin.username
            target = request.args.get("next", "")
            if not target.startswith("/admin") or target.startswith("//"):
                target = url_for("admin.dashboard")
            return redirect(target)
        error = "Wrong username or password."
    return render_template("admin/login.html", error=error)


@bp.post("/logout")
def logout():
    session.pop("admin_id", None)
    session.pop("admin_name", None)
    flash("You have been signed out.", "success")
    return redirect(url_for("admin.login"))


# ---------------------------------------------------------------- dashboard

def _change(current, previous) -> float | None:
    """Percent change, or None when there is nothing to compare with."""
    if not previous:
        return None
    return float((Decimal(current) - Decimal(previous)) / Decimal(previous) * 100)


@bp.get("/")
@admin_required
def dashboard():
    payments.expire_stale_orders()
    days = request.args.get("days", 30, type=int)
    if days not in RANGES:
        days = 30

    # Day boundaries follow Cambodia time; the database stores UTC.
    today = (utcnow() + CAMBODIA_OFFSET).date()
    start_day = today - timedelta(days=days - 1)
    prev_start_day = start_day - timedelta(days=days)
    to_utc = lambda d: datetime.combine(d, datetime.min.time()) - CAMBODIA_OFFSET  # noqa: E731
    start, prev_start = to_utc(start_day), to_utc(prev_start_day)

    paid = db.session.execute(
        select(Order.id, Order.created_at, Order.total, Order.email)
        .where(Order.status == Order.STATUS_PAID, Order.created_at >= prev_start)
    ).all()
    current = [o for o in paid if o.created_at >= start]
    previous = [o for o in paid if o.created_at < start]

    def totals(orders):
        revenue = sum((o.total for o in orders), Decimal("0"))
        customers = len({o.email.lower() for o in orders})
        return revenue, len(orders), customers, (revenue / len(orders) if orders else Decimal("0"))

    cur, prev = totals(current), totals(previous)
    kpis = [
        {"label": "Total sales", "value": cur[0], "money": True, "change": _change(cur[0], prev[0]), "icon": "bag", "tone": "green"},
        {"label": "Total orders", "value": cur[1], "change": _change(cur[1], prev[1]), "icon": "cart", "tone": "blue"},
        {"label": "Customers", "value": cur[2], "change": _change(cur[2], prev[2]), "icon": "users", "tone": "violet"},
        {"label": "Avg. order value", "value": cur[3], "money": True, "change": _change(cur[3], prev[3]), "icon": "trend", "tone": "orange"},
    ]

    # Daily revenue for this period and the one before it, aligned day by day.
    by_day = defaultdict(Decimal)
    for o in paid:
        by_day[(o.created_at + CAMBODIA_OFFSET).date()] += o.total
    chart = {
        "labels": [f"{d:%b} {d.day}" for d in (start_day + timedelta(days=i) for i in range(days))],
        "current": [float(by_day[start_day + timedelta(days=i)]) for i in range(days)],
        "previous": [float(by_day[prev_start_day + timedelta(days=i)]) for i in range(days)],
    }

    # Revenue per product and per category in this period.
    lines = db.session.execute(
        select(OrderItem.product_id, OrderItem.product_name, OrderItem.unit_price, OrderItem.quantity, Category.name)
        .join(Order, Order.id == OrderItem.order_id)
        .outerjoin(Product, Product.id == OrderItem.product_id)
        .outerjoin(Category, Category.id == Product.category_id)
        .where(Order.status == Order.STATUS_PAID, Order.created_at >= start)
    ).all()
    per_product, per_category = {}, defaultdict(Decimal)
    for product_id, name, price, qty, category in lines:
        entry = per_product.setdefault(product_id or name, {"id": product_id, "name": name, "revenue": Decimal("0"), "sold": 0})
        entry["revenue"] += price * qty
        entry["sold"] += qty
        per_category[category or "Uncategorized"] += price * qty
    top_products = sorted(per_product.values(), key=lambda e: e["revenue"], reverse=True)[:4]
    products_by_id = {p.id: p for p in Product.query.filter(Product.id.in_([e["id"] for e in top_products if e["id"]])).all()}
    for entry in top_products:
        entry["product"] = products_by_id.get(entry["id"])
    category_total = sum(per_category.values(), Decimal("0"))
    categories = [
        {"name": name, "revenue": value, "share": float(value / category_total * 100) if category_total else 0}
        for name, value in sorted(per_category.items(), key=lambda kv: kv[1], reverse=True)
    ]

    recent = Order.query.order_by(Order.created_at.desc(), Order.id.desc()).limit(6).all()
    low_stock = Product.query.filter(Product.status == Product.STATUS_ACTIVE, Product.stock <= 5).order_by(Product.stock).limit(5).all()
    return render_template(
        "admin/dashboard.html", days=days, ranges=RANGES, kpis=kpis, chart=chart,
        top_products=top_products, categories=categories, recent=recent, low_stock=low_stock,
        cfg=current_app.config,
    )


# ---------------------------------------------------------------- products

@bp.get("/products")
@admin_required
def products():
    q = request.args.get("q", "").strip()
    category_id = request.args.get("category", type=int)
    query = select(Product)
    if q:
        query = query.where(Product.name.ilike(f"%{q}%"))
    if category_id:
        query = query.where(Product.category_id == category_id)
    items = db.session.execute(query.order_by(Product.id)).scalars().all()
    return render_template("admin/products.html", products=items, q=q, category_id=category_id,
                           categories=Category.query.order_by(Category.name).all())


def _money(raw: str, *, required: bool) -> Decimal | None:
    raw = raw.strip()
    if not raw and not required:
        return None
    value = Decimal(raw)
    if value <= 0 or value >= Decimal("100000000") or value.as_tuple().exponent < -2:
        raise InvalidOperation
    return value


def _read_product_form() -> tuple[dict, dict, tuple[bytes, str] | None]:
    form = request.form
    data = {
        "name": form.get("name", "").strip(),
        "description": form.get("description", "").strip(),
        "price": form.get("price", "").strip(),
        "compare_price": form.get("compare_price", "").strip(),
        "stock": form.get("stock", "").strip(),
        "status": form.get("status", Product.STATUS_ACTIVE),
        "category_id": form.get("category_id", type=int),
    }
    errors = {}
    if not data["name"]:
        errors["name"] = "Name is required."
    elif len(data["name"]) > 120:
        errors["name"] = "Name must be 120 characters or fewer."
    try:
        data["price"] = _money(data["price"], required=True)
    except (InvalidOperation, ValueError):
        errors["price"] = "Enter a price greater than 0 with at most 2 decimals, e.g. 12.50."
    try:
        data["compare_price"] = _money(data["compare_price"], required=False)
        if data["compare_price"] is not None and "price" not in errors and data["compare_price"] <= data["price"]:
            errors["compare_price"] = "The original price must be higher than the price (or leave it empty)."
    except (InvalidOperation, ValueError):
        errors["compare_price"] = "Enter a valid amount, or leave it empty."
    try:
        stock = int(data["stock"])
        if stock < 0 or stock > 1_000_000:
            raise ValueError
        data["stock"] = stock
    except ValueError:
        errors["stock"] = "Enter a whole number of 0 or more."
    if data["status"] not in Product.STATUSES:
        errors["status"] = "Choose Active or Inactive."
    if data["category_id"] and not db.session.get(Category, data["category_id"]):
        data["category_id"] = None

    image = None
    upload = request.files.get("image")
    if upload and upload.filename:
        raw = upload.read()
        mime = _detect_image_type(raw)
        if not mime:
            errors["image"] = "This file isn't a JPG, PNG, WEBP, GIF or AVIF image (it may only be named like one)."
        else:
            image = (raw, mime)
    return data, errors, image


def _render_product_form(product, form, errors, status=200):
    return render_template("admin/product_form.html", product=product, form=form, errors=errors,
                           categories=Category.query.order_by(Category.name).all()), status


def _save_product(product: Product | None):
    data, errors, image = _read_product_form()
    if errors:
        return _render_product_form(product, data, errors, 400)
    is_new = product is None
    product = product or Product()
    for field in ("name", "description", "price", "compare_price", "stock", "status", "category_id"):
        setattr(product, field, data[field])
    if image:
        product.image_data, product.image_mime = image
        product.image_version = (product.image_version or 0) + 1
    elif request.form.get("remove_image") and not is_new:
        product.image_data, product.image_mime = None, None
        product.image_version = (product.image_version or 0) + 1
    db.session.add(product)
    db.session.commit()
    flash(f"Product “{product.name}” {'created' if is_new else 'updated'}.", "success")
    return redirect(url_for("admin.products"))


@bp.route("/products/new", methods=["GET", "POST"])
@admin_required
def product_new():
    if request.method == "POST":
        return _save_product(None)
    return _render_product_form(None, {"status": Product.STATUS_ACTIVE, "stock": 0,
                                       "category_id": request.args.get("category", type=int)}, {})


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def product_edit(product_id):
    product = db.session.get(Product, product_id) or abort(404)
    if request.method == "POST":
        return _save_product(product)
    form = {"name": product.name, "description": product.description, "price": product.price,
            "compare_price": product.compare_price, "stock": product.stock, "status": product.status,
            "category_id": product.category_id}
    return _render_product_form(product, form, {})


@bp.post("/products/<int:product_id>/delete")
@admin_required
def product_delete(product_id):
    product = db.session.get(Product, product_id) or abort(404)
    # Past orders keep their copied name and price; just unlink them from the product.
    OrderItem.query.filter_by(product_id=product.id).update({"product_id": None})
    db.session.delete(product)
    db.session.commit()
    flash(f"Product “{product.name}” deleted.", "success")
    return redirect(url_for("admin.products"))


# ---------------------------------------------------------------- categories

@bp.get("/categories")
@admin_required
def categories():
    counts = dict(db.session.execute(
        select(Product.category_id, func.count(Product.id)).group_by(Product.category_id)
    ).all())
    items = Category.query.order_by(Category.name).all()
    return render_template("admin/categories.html", categories=items, counts=counts,
                           uncategorized=counts.get(None, 0))


def _save_category(category: Category | None):
    name = request.form.get("name", "").strip()
    error = None
    if not name:
        error = "Name is required."
    elif len(name) > 60:
        error = "Name must be 60 characters or fewer."
    else:
        clash = Category.query.filter(func.lower(Category.name) == name.lower()).first()
        if clash and clash is not category:
            error = "A category with this name already exists."
    if error:
        return render_template("admin/category_form.html", category=category, name=name, error=error), 400
    is_new = category is None
    category = category or Category()
    category.name = name
    db.session.add(category)
    db.session.commit()
    flash(f"Category “{name}” {'created' if is_new else 'updated'}.", "success")
    return redirect(url_for("admin.categories"))


@bp.route("/categories/new", methods=["GET", "POST"])
@admin_required
def category_new():
    if request.method == "POST":
        return _save_category(None)
    return render_template("admin/category_form.html", category=None, name="", error=None)


@bp.route("/categories/<int:category_id>/edit", methods=["GET", "POST"])
@admin_required
def category_edit(category_id):
    category = db.session.get(Category, category_id) or abort(404)
    if request.method == "POST":
        return _save_category(category)
    return render_template("admin/category_form.html", category=category, name=category.name, error=None)


@bp.post("/categories/<int:category_id>/delete")
@admin_required
def category_delete(category_id):
    category = db.session.get(Category, category_id) or abort(404)
    Product.query.filter_by(category_id=category.id).update({"category_id": None})
    db.session.delete(category)
    db.session.commit()
    flash(f"Category “{category.name}” deleted. Its products are now uncategorized.", "success")
    return redirect(url_for("admin.categories"))


# ---------------------------------------------------------------- orders

@bp.get("/orders")
@admin_required
def orders():
    payments.expire_stale_orders()
    status = request.args.get("status", "")
    q = request.args.get("q", "").strip()
    query = select(Order)
    if status in Order.STATUSES:
        query = query.where(Order.status == status)
    if q:
        number = q.upper().removeprefix("ORD-").lstrip("0")
        conditions = [Order.customer_name.ilike(f"%{q}%"), Order.phone.ilike(f"%{q}%"), Order.email.ilike(f"%{q}%")]
        if number.isdigit():
            conditions.append(Order.id == int(number))
        query = query.where(or_(*conditions))
    page = db.paginate(query.order_by(Order.created_at.desc(), Order.id.desc()),
                       page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    counts = dict(db.session.execute(select(Order.status, func.count(Order.id)).group_by(Order.status)).all())
    return render_template("admin/orders.html", page=page, status=status, q=q, counts=counts)


@bp.get("/orders/<int:order_id>")
@admin_required
def order_detail(order_id):
    order = db.session.get(Order, order_id) or abort(404)
    payments.refresh_status(order)
    return render_template("admin/order_detail.html", order=order)


@bp.post("/orders/<int:order_id>/mark-paid")
@admin_required
def order_mark_paid(order_id):
    """Manual confirmation, e.g. after checking the bank app when the Bakong API isn't reachable."""
    order = db.session.get(Order, order_id) or abort(404)
    if order.is_pending:
        payments.mark_paid(order, f"admin:{session.get('admin_name', '')}")
        db.session.commit()
        flash(f"{order.number} marked as paid.", "success")
    else:
        flash("Only pending orders can be marked as paid.", "error")
    return redirect(url_for("admin.order_detail", order_id=order.id))


# ---------------------------------------------------------------- customers

@bp.get("/customers")
@admin_required
def customers():
    """Guests have no accounts, so customers are grouped from paid orders by email address."""
    q = request.args.get("q", "").strip().lower()
    rows = Order.query.filter_by(status=Order.STATUS_PAID).order_by(Order.created_at.desc()).all()
    people = {}
    for order in rows:
        key = order.email.lower()
        person = people.setdefault(key, {"name": order.customer_name, "email": order.email, "phone": order.phone,
                                         "address": order.shipping_address, "orders": 0,
                                         "spent": Decimal("0"), "last": order.created_at, "last_id": order.id})
        person["orders"] += 1
        person["spent"] += order.total
    items = sorted(people.values(), key=lambda p: p["spent"], reverse=True)
    if q:
        items = [p for p in items if q in p["name"].lower() or q in p["email"].lower() or q in p["phone"]]
    return render_template("admin/customers.html", customers=items, q=q, total=len(people))
