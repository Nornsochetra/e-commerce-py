"""Small helpers: CSRF protection for forms and the admin login guard."""

import hmac
import secrets
from functools import wraps

from flask import abort, current_app, redirect, request, session, url_for


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def verify_csrf() -> None:
    """Reject state-changing requests that don't carry this session's CSRF token."""
    if not current_app.config.get("CSRF_ENABLED", True):
        return
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf", "")
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, description="Your session expired. Please go back, refresh the page and try again.")


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapper
