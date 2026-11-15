"""Setec Shop: a mini e-commerce site with KHQR checkout and an admin area."""

from datetime import timedelta
from decimal import Decimal

import click
from dotenv import load_dotenv
from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from . import cart
from .config import load_config
from .models import AdminUser, db
from .security import csrf_token, verify_csrf

CAMBODIA_OFFSET = timedelta(hours=7)  # Asia/Phnom_Penh, no daylight saving


def create_app(overrides: dict | None = None) -> Flask:
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(load_config())
    if overrides:
        app.config.update(overrides)

    # Render (and most hosts) sit behind a proxy: trust its X-Forwarded-* headers for https links.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)

    from .routes.admin import bp as admin_bp
    from .routes.shop import bp as shop_bp

    app.register_blueprint(shop_bp)
    app.register_blueprint(admin_bp)

    app.before_request(verify_csrf)
    _register_template_helpers(app)
    _register_error_pages(app)
    _register_commands(app)
    return app


def _register_template_helpers(app: Flask) -> None:
    app.jinja_env.globals["csrf_token"] = csrf_token  # a global, so imported macros can use it too

    @app.context_processor
    def inject_globals():
        from .models import Category

        return {
            "nav_categories": Category.query.order_by(Category.name).all(),
            "shop_name": app.config["SHOP_NAME"],
            "cart_count": cart.count(),
            "payment_mode": app.config["PAYMENT_MODE"],
        }

    @app.template_filter("money")
    def money(value, currency="USD"):
        amount = Decimal(value or 0)
        return f"${amount:,.2f}" if currency == "USD" else f"{amount:,.0f}៛"

    @app.template_filter("localtime")
    def localtime(value, fmt="%d %b %Y, %H:%M"):
        return (value + CAMBODIA_OFFSET).strftime(fmt) if value else "—"


def _register_error_pages(app: Flask) -> None:
    def page(code, title, message):
        return render_template("errors/error.html", code=code, title=title, message=message), code

    app.register_error_handler(400, lambda e: page(400, "Bad request", e.description))
    app.register_error_handler(404, lambda e: page(404, "Page not found", "We couldn't find that page."))
    app.register_error_handler(
        413, lambda e: page(413, "File too large", "Images must be smaller than 5 MB.")
    )
    app.register_error_handler(
        500, lambda e: page(500, "Something went wrong", "Please try again in a moment.")
    )


def init_database(app: Flask, seed: bool = True) -> None:
    """Create tables, the first admin account, and sample products when the shop is empty."""
    from .seed import seed_products, upgrade_schema

    with app.app_context():
        db.create_all()
        upgrade_schema()
        if not AdminUser.query.first():
            admin = AdminUser(username=app.config["ADMIN_USERNAME"])
            admin.set_password(app.config["ADMIN_PASSWORD"])
            db.session.add(admin)
            db.session.commit()
            app.logger.info("Created admin account '%s'", admin.username)
        if seed:
            seed_products()


def _register_commands(app: Flask) -> None:
    @app.cli.command("init-db")
    @click.option("--no-seed", is_flag=True, help="Don't add sample products.")
    def init_db_command(no_seed):
        """Create tables, the admin account and sample products (safe to run on every deploy)."""
        init_database(app, seed=not no_seed)
        click.echo("Database ready.")

    @app.cli.command("set-admin-password")
    @click.argument("username")
    @click.password_option()
    def set_admin_password(username, password):
        """Create an admin account or change its password."""
        admin = AdminUser.query.filter_by(username=username).first() or AdminUser(username=username)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        click.echo(f"Password saved for '{username}'.")
