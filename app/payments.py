"""KHQR payment lifecycle for orders: create the QR, check Bakong, mark paid / cancel / expire."""

import logging
from datetime import timedelta

import requests
from flask import current_app

from . import khqr
from .models import Order, Product, db, utcnow

log = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 3


def attach_khqr(order: Order) -> None:
    """Generate the one-time KHQR for an order (the order must already have an id)."""
    cfg = current_app.config
    minutes = cfg["PAYMENT_TIMEOUT_MINUTES"]
    if cfg["BAKONG_KHQR_TEMPLATE"]:
        order.khqr = khqr.build_from_template(
            cfg["BAKONG_KHQR_TEMPLATE"],
            amount=order.total,
            currency=order.currency,
            bill_number=order.number,
            expires_in_seconds=minutes * 60,
        )
    else:
        order.khqr = _build_from_settings(order, cfg, minutes)
    order.khqr_md5 = khqr.md5(order.khqr)
    order.expires_at = utcnow() + timedelta(minutes=minutes)


def _build_from_settings(order: Order, cfg, minutes: int) -> str:
    return khqr.build_khqr(
        account_id=cfg["BAKONG_ACCOUNT_ID"],
        account_information=cfg["BAKONG_ACCOUNT_INFO"] or None,
        acquiring_bank=cfg["BAKONG_ACQUIRING_BANK"] or None,
        merchant_name=cfg["MERCHANT_NAME"],
        merchant_city=cfg["MERCHANT_CITY"],
        amount=order.total,
        currency=order.currency,
        bill_number=order.number,
        store_label=cfg["SHOP_NAME"],
        expires_in_seconds=minutes * 60,
    )


def mark_paid(order: Order, reference: str) -> None:
    if order.status != Order.STATUS_PENDING:
        return
    order.status = Order.STATUS_PAID
    order.paid_at = utcnow()
    order.payment_ref = reference[:128]


def release(order: Order, status: str) -> None:
    """Cancel or expire a pending order and put its reserved stock back."""
    if order.status != Order.STATUS_PENDING:
        return
    for item in order.items:
        if item.product_id:
            product = db.session.get(Product, item.product_id)
            if product:
                product.stock += item.quantity
    order.status = status


def expire_stale_orders() -> int:
    """Expire every pending order whose KHQR has timed out. Returns how many were expired."""
    stale = Order.query.filter(Order.status == Order.STATUS_PENDING, Order.expires_at < utcnow()).all()
    for order in stale:
        release(order, Order.STATUS_EXPIRED)
    if stale:
        db.session.commit()
    return len(stale)


def check_bakong(order: Order) -> dict | None:
    """Ask Bakong whether this order's KHQR was paid. Returns the transaction data, or None if unpaid.

    Raises requests.RequestException / ValueError when Bakong can't be reached or rejects the token.
    """
    cfg = current_app.config
    response = requests.post(
        f"{cfg['BAKONG_API_URL']}/check_transaction_by_md5",
        json={"md5": order.khqr_md5},
        headers={"Authorization": f"Bearer {cfg['BAKONG_TOKEN']}"},
        timeout=10,
    )
    if response.status_code in (401, 403):
        raise ValueError(f"Bakong rejected the request (HTTP {response.status_code})")
    body = response.json()
    data = body.get("data")
    if body.get("responseCode") == 0 and isinstance(data, dict):
        to_account = data.get("toAccountId")
        ours = khqr.template_account_id(cfg["BAKONG_KHQR_TEMPLATE"]) or cfg["BAKONG_ACCOUNT_ID"]
        if to_account and to_account != ours:
            log.warning("Order %s: Bakong payment went to %s, not our account", order.number, to_account)
            return None
        return data
    return None


def refresh_status(order: Order) -> str | None:
    """Bring a pending order up to date. Returns a warning message if Bakong could not be checked."""
    if order.status != Order.STATUS_PENDING:
        return None
    now = utcnow()
    warning = None
    if current_app.config["PAYMENT_MODE"] == "bakong":
        recently = order.last_checked_at and (now - order.last_checked_at).total_seconds() < CHECK_INTERVAL_SECONDS
        if not recently:
            order.last_checked_at = now
            try:
                paid = check_bakong(order)
                if paid:
                    mark_paid(order, str(paid.get("hash") or "bakong"))
            except (requests.RequestException, ValueError) as exc:
                log.warning("Bakong check failed for %s: %s", order.number, exc)
                warning = "We couldn't reach Bakong to check the payment. We'll keep trying."
    if order.is_pending and order.expires_at and order.expires_at < now:
        release(order, Order.STATUS_EXPIRED)
    db.session.commit()
    return warning
