# Setec Shop

A mini e-commerce web store built with **Python (Flask)**. Customers browse products, share them to Facebook and Telegram, fill a cart and pay with **KHQR (Bakong)**. Admins manage products and view order history.

Setec Institute — Year 4 Python final project.

| | |
|---|---|
| **Live demo** | `https://<your-app>.onrender.com` |
| **Admin URL** | `https://<your-app>.onrender.com/admin` |
| **Admin login** | username `admin` · password: set with `ADMIN_PASSWORD` |
| **Source code** | `https://github.com/<you>/setec-shop` |

## Features

**Customer pages (no account needed)**

| Page | URL | What it does |
|---|---|---|
| Home | `/` | Hero slider, feature strip, popular categories, best-selling product grid (name, price, description, thumbnail, **View details**, **Add to cart**) |
| Shop | `/shop` | All products with search, category and deal filters, sorting and paging |
| Product details | `/products/<id>` | Full description, price, stock status, image, quantity selector, **Add to cart**, share to **Facebook** / **Telegram** (with Open Graph previews) and copy link |
| Cart | `/cart` | Quantity, unit price, subtotal per line and total; change quantity or remove; **Proceed to checkout** |
| Checkout | `/checkout` | Guest form: full name, email, phone, shipping address (validated on the server) |
| KHQR payment | `/orders/<token>/pay` | One-time **KHQR** code with the exact amount and a 15-minute countdown; the page polls and moves on as soon as the payment is confirmed |
| Order confirmation | `/orders/<token>` | Success message, **Order ID**, customer details, items and **total amount** |

**Admin pages (`/admin`, sign-in required)**

| Page | What it does |
|---|---|
| Dashboard | Total sales, orders, customers and average order value vs the previous period (7/30/90 days); daily sales chart; top products; recent orders; sales by category; low stock; KHQR status |
| Products | Table with ID, image, name, category, price, stock, status (Active/Inactive); **Add new product**, **Edit**, **Delete** |
| Product form | Name, description, category, price, optional original price (shows a discount), stock quantity, image upload (JPG/PNG/WEBP/GIF, stored in the database), status |
| Categories | Add, rename and delete categories |
| Order history | Table with Order ID, customer name, phone, total, order date and status; status tabs and search |
| Customers | Guests grouped by email from paid orders: orders, total spent, last order |
| Order details | Purchased items, quantities, subtotals, total, shipping address, payment info, and **Mark as paid** for manual confirmation |

**Behind the scenes**
- Stock is checked when adding to the cart and again at checkout. Placing an order reserves the stock, locking the rows in PostgreSQL. A cancelled or expired order puts the stock back.
- Orders keep a copy of each item's name and price, so deleting or repricing a product never changes past orders.
- Customer order pages use an unguessable token in the URL, not the numeric ID.
- All forms are CSRF-protected. Passwords are hashed. Uploaded images are checked by their file content, and SVG uploads are refused.

## KHQR payment

The app builds the KHQR string itself, following the EMVCo / NBC KHQR spec (`app/khqr.py`). The string holds your Bakong account, the amount in USD, the order number as the bill number, creation and expiry timestamps, and a CRC16 checksum. It is drawn as an SVG QR code and can be scanned by ABA, ACLEDA, Wing, Bakong and other KHQR apps.

How the shop learns that an order was paid:

| Mode | When | How |
|---|---|---|
| **Bakong** | `BAKONG_TOKEN` is set | Every 3 seconds the server asks Bakong `POST /v1/check_transaction_by_md5` with the MD5 of the KHQR string; when Bakong reports the transaction, the order becomes **Paid** |
| **Demo** | no token | The payment page shows a **Simulate successful payment** button so the full flow can be shown without real money |
| **Manual** | any mode | An admin opens the order and clicks **Mark as paid** after seeing the money arrive in the bank app |

> **Important:** Bakong's API only accepts requests from Cambodian IP addresses. A server on Render (USA/Europe/Singapore) gets `403`, and the payment page then says "We couldn't reach Bakong". For a live demo, use **demo mode** or **Mark as paid**. You can also set `BAKONG_API_URL` to a relay server hosted in Cambodia. Automatic detection works when the app runs on a machine in Cambodia (e.g. your laptop with `BAKONG_TOKEN` set).

To get the values:
- `BAKONG_ACCOUNT_ID`: your Bakong account ID, shown in the Bakong app profile (looks like `name@aclb`, `name@abaa`, `name@wing`). **Use your real one**, otherwise banking apps will reject the QR code.
- `BAKONG_TOKEN`: register at <https://api-bakong.nbc.gov.kh/register>. The token expires every 90 days.

## Run locally

Requires Python 3.12 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # then edit BAKONG_ACCOUNT_ID etc.
python run.py
```

Open <http://127.0.0.1:8000>. The admin is at <http://127.0.0.1:8000/admin> (`admin` / `admin123` unless you changed `.env`).

On first start, the app creates a SQLite database in `instance/shop.db` with the admin account and 8 sample products. The sample products have simple generated pictures; upload real photos from the admin product form.

Run the tests (34 tests: KHQR encoding, cart, checkout, payment modes, stock, admin CRUD, auth, CSRF):

```bash
pytest
```

Change an admin password, or add another admin:

```bash
flask --app wsgi set-admin-password admin
```

## Configuration

All settings come from environment variables (or `.env` locally). See `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `SHOP_NAME` | `Setec Shop` | Name shown in the header, page titles and KHQR store label |
| `SECRET_KEY` | random, saved in `instance/` | Signs sessions/cart cookies. **Set it in production** |
| `DATABASE_URL` | SQLite file | PostgreSQL URL in production (`postgres://…` is accepted) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `admin123` | First admin account, created only when no admin exists |
| `BAKONG_ACCOUNT_ID` | `yourname@aclb` | Bakong account that receives payments |
| `BAKONG_ACCOUNT_INFO` / `BAKONG_ACQUIRING_BANK` | empty | For banks with one shared Bakong ID (ABA: `abaakhppxxx@abaa`): your account number and bank name, copied from your own bank KHQR |
| `MERCHANT_NAME` / `MERCHANT_CITY` | shop name / `Phnom Penh` | Shown in the banking app when scanning (max 25 / 15 characters) |
| `BAKONG_KHQR_TEMPLATE` | empty | **Recommended for ABA.** The text of your own bank "Receive money" KHQR (starts with `000201`). The shop copies its account fields exactly and only changes the amount, bill number and expiry, so the bank app accepts the payment. Replaces the three settings above |
| `BAKONG_TOKEN` | empty → demo mode | Bakong developer token for automatic payment detection |
| `BAKONG_API_URL` | `https://api-bakong.nbc.gov.kh/v1` | Change to use a relay |
| `PAYMENT_TIMEOUT_MINUTES` | `15` | KHQR lifetime; unpaid orders then expire and release stock |
| `SESSION_COOKIE_SECURE` | off | Set `true` when served over HTTPS |

## Deploy to Render (free)

1. Push this folder to a GitHub repository.
2. On <https://render.com>: **New → Blueprint** and select the repository. `render.yaml` creates:
   - a free **web service** (`gunicorn wsgi:app`; every start runs `flask init-db` first, which only creates what is missing);
   - a free **PostgreSQL** database, connected through `DATABASE_URL`.
3. When asked, fill in `ADMIN_PASSWORD`, `BAKONG_ACCOUNT_ID` and, optionally, `BAKONG_TOKEN`.
4. Wait for the deploy to finish, then open the URL shown on the dashboard.

Notes:
- Free web services sleep after 15 minutes without visitors; the first request then takes about a minute. Open the site once before recording or presenting.
- Render's free PostgreSQL is deleted **30 days** after creation. For a longer-lived demo, create a free database at <https://neon.tech> and paste its connection string as `DATABASE_URL` (then remove the `databases:` section from `render.yaml`).
- Product images live in the database, so they survive redeploys.

## Project structure

```
app/
  __init__.py        create_app(), template filters, error pages, CLI commands
  config.py          settings from environment variables
  models.py          Product, Order, OrderItem, AdminUser (SQLAlchemy)
  khqr.py            KHQR string builder, CRC16, QR rendering
  payments.py        KHQR lifecycle: create, check Bakong, mark paid, cancel/expire
  cart.py            session cart
  security.py        CSRF tokens, admin login guard
  seed.py            sample products
  routes/shop.py     customer pages
  routes/admin.py    admin pages
  templates/         Jinja templates (shop/, admin/, errors/)
  static/            CSS, JS, images
tests/               pytest suite
run.py               local development server
wsgi.py              production entry point (gunicorn)
render.yaml          Render Blueprint
```

## Demo video checklist

1. Home page: product grid, search, an out-of-stock product.
2. Product details: stock status, quantity selector, add to cart, share to Facebook and Telegram (show the link preview).
3. Cart: change a quantity, remove an item, see the totals update, proceed to checkout.
4. Checkout: submit an empty form to show validation, then fill in the details.
5. KHQR page: the code, amount and countdown. Scan it with a banking app to show it is a real KHQR, then pay (or simulate the payment).
6. Order confirmation: Order ID, customer details, total.
7. Admin: sign in, the product table, add a product with an image, edit it (set it Inactive and show it disappears from the shop), delete one.
8. Admin orders: the new order in the table, its details (items, quantities, subtotals, shipping address).
