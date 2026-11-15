"""Guest shopping cart, kept in the signed session cookie as {product_id: quantity}."""

from dataclasses import dataclass
from decimal import Decimal

from flask import session

from .models import Product, db

MAX_QUANTITY_PER_ITEM = 99


@dataclass
class CartLine:
    product: Product
    quantity: int

    @property
    def subtotal(self) -> Decimal:
        return self.product.price * self.quantity

    @property
    def over_stock(self) -> bool:
        return self.quantity > self.product.stock


def _raw() -> dict[str, int]:
    cart = session.get("cart")
    return cart if isinstance(cart, dict) else {}


def _save(cart: dict[str, int]) -> None:
    session["cart"] = cart
    session.modified = True


def count() -> int:
    return sum(_raw().values())


def quantity_of(product_id: int) -> int:
    return _raw().get(str(product_id), 0)


def set_quantity(product_id: int, quantity: int) -> None:
    cart = _raw()
    quantity = max(0, min(quantity, MAX_QUANTITY_PER_ITEM))
    if quantity == 0:
        cart.pop(str(product_id), None)
    else:
        cart[str(product_id)] = quantity
    _save(cart)


def remove(product_id: int) -> None:
    set_quantity(product_id, 0)


def clear() -> None:
    session.pop("cart", None)


def lines() -> list[CartLine]:
    """Cart lines for products that still exist and are active (others are dropped from the cart)."""
    cart = _raw()
    if not cart:
        return []
    ids = [int(pid) for pid in cart]
    products = {p.id: p for p in db.session.query(Product).filter(Product.id.in_(ids)).all()}
    result, cleaned = [], {}
    for pid, qty in cart.items():
        product = products.get(int(pid))
        if product and product.is_active:
            result.append(CartLine(product, qty))
            cleaned[pid] = qty
    if cleaned != cart:
        _save(cleaned)
    return result


def total(cart_lines: list[CartLine]) -> Decimal:
    return sum((line.subtotal for line in cart_lines), Decimal("0.00"))
