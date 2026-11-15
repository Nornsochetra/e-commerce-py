"""Sample categories and products so a fresh shop isn't empty, plus small schema upgrades.

Sample products get a simple generated picture; replace them with real photos from the admin product form.
"""

from decimal import Decimal

from sqlalchemy import inspect, text

from .models import Category, Product, db

CATEGORIES = ["Pantry", "Coffee & Tea", "Fashion", "Home & Living"]

# name, price, compare_price, stock, emoji, category, description
SAMPLES = [
    ("Kampot Pepper Gift Box", "12.50", "15.00", 40, "🌶️", "Pantry",
     "Hand-picked black, red and white Kampot pepper in a reusable palm-leaf box. "
     "Kampot pepper has a protected geographical indication and a warm, floral heat. 3 x 50 g."),
    ("Handwoven Krama Scarf", "8.00", None, 60, "🧣", "Fashion",
     "The classic Cambodian checked scarf, woven on a wooden loom from soft cotton. "
     "Use it as a scarf, a sun shade or a light towel. 160 x 60 cm."),
    ("Mondulkiri Wild Honey", "9.75", None, 25, "🍯", "Pantry",
     "Raw forest honey collected by local communities in Mondulkiri province. "
     "Unfiltered and unheated, with a deep caramel taste. 500 g glass jar."),
    ("Ratanakiri Coffee Beans", "7.20", "9.00", 35, "☕", "Coffee & Tea",
     "Medium-roast robusta and arabica beans grown on the red soil of Ratanakiri. "
     "Notes of dark chocolate and roasted nuts. 250 g, whole bean."),
    ("Palm Sugar Cubes", "5.50", None, 80, "🍬", "Pantry",
     "Natural sugar from the sap of the sugar palm, cooked slowly over a wood fire. "
     "Perfect for desserts, curries and coffee. 1 kg bag."),
    ("Silk Cushion Cover", "15.00", None, 12, "🧵", "Home & Living",
     "Golden silk woven in Takeo with a traditional pattern. Hidden zip, cushion not included. 45 x 45 cm."),
    ("Rattan Market Basket", "18.00", None, 0, "🧺", "Home & Living",
     "A sturdy hand-woven rattan basket for shopping and storage. Strong leather handles. "
     "Currently out of stock — check back soon."),
    ("Lotus Scented Candle", "6.90", None, 50, "🕯️", "Home & Living",
     "Soy-wax candle with a fresh lotus scent, poured by hand in Phnom Penh. Burns for about 30 hours."),
]


def sample_svg(emoji: str) -> bytes:
    """A light studio-style picture: soft gray background, a gentle shadow and the product emoji."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 600">
<defs>
<radialGradient id="bg" cx="50%" cy="40%" r="75%"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#eef1ee"/></radialGradient>
<radialGradient id="sh" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#000" stop-opacity=".16"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>
</defs>
<rect width="600" height="600" fill="url(#bg)"/>
<ellipse cx="300" cy="445" rx="150" ry="26" fill="url(#sh)"/>
<text x="300" y="290" font-size="250" text-anchor="middle" dominant-baseline="central">{emoji}</text>
</svg>""".encode()


def upgrade_schema() -> None:
    """Add columns introduced after the first release to an existing database (SQLite or PostgreSQL)."""
    columns = {c["name"] for c in inspect(db.engine).get_columns("products")}
    statements = []
    if "compare_price" not in columns:
        statements.append("ALTER TABLE products ADD COLUMN compare_price NUMERIC(10, 2)")
    if "category_id" not in columns:
        statements.append("ALTER TABLE products ADD COLUMN category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL")
    if statements:
        with db.engine.begin() as conn:
            for sql in statements:
                conn.execute(text(sql))


def seed_categories() -> None:
    """Create the sample categories once, and file the sample products into them."""
    if Category.query.first():
        return
    by_name = {name: Category(name=name) for name in CATEGORIES}
    db.session.add_all(by_name.values())
    db.session.flush()
    samples = {s[0]: s for s in SAMPLES}
    for product in Product.query.all():
        sample = samples.get(product.name)
        if not sample or product.category_id:
            continue
        _, _, compare, _, emoji, category, _ = sample
        product.category_id = by_name[category].id
        if compare and product.compare_price is None:
            product.compare_price = Decimal(compare)
        if product.image_mime == "image/svg+xml":  # still the generated picture: refresh its style
            product.image_data = sample_svg(emoji)
            product.image_version = (product.image_version or 0) + 1
    db.session.commit()


def seed_products() -> int:
    """Add the sample products if there are no products at all. Returns how many were added."""
    if Product.query.first():
        seed_categories()
        return 0
    for name, price, compare, stock, emoji, _category, description in SAMPLES:
        db.session.add(Product(
            name=name, description=description, price=Decimal(price),
            compare_price=Decimal(compare) if compare else None, stock=stock,
            status=Product.STATUS_ACTIVE, image_data=sample_svg(emoji),
            image_mime="image/svg+xml", image_version=1,
        ))
    db.session.commit()
    seed_categories()
    return len(SAMPLES)
