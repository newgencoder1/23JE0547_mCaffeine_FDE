"""Login / logout / current user, plus the `login_required` guard.

Sessions: after a correct password we store only the user's id in Flask's signed,
HttpOnly session cookie. On every request the user is re-loaded from the
database, so a deleted user or changed role takes effect immediately.
"""
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request, session

from .db import query_one
from .errors import ApiError

bp = Blueprint("auth", __name__)

# Used when the username does not exist, so that a wrong username takes as long as
# a wrong password (no user enumeration by timing). Created once, on first use.
_dummy_hash = None


def _get_dummy_hash():
    global _dummy_hash
    if _dummy_hash is None:
        import secrets

        _dummy_hash = hash_password(secrets.token_hex(16))
    return _dummy_hash


def hash_password(plain):
    import bcrypt

    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def check_password(plain, hashed):
    import bcrypt

    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8") if isinstance(hashed, str) else hashed)
    except ValueError:  # malformed hash
        return False


def public_user(user):
    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "is_creator": bool(user["is_creator"]),
        "is_approver": bool(user["is_approver"]),
    }


def login_required(view):
    """RULE 1: no valid login -> 401, on every API endpoint that uses this decorator."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        user_id = session.get("user_id")
        user = None
        if user_id is not None:
            user = query_one(
                "SELECT id, username, email, is_creator, is_approver FROM users WHERE id = %s",
                (user_id,),
            )
        if user is None:
            session.clear()
            raise ApiError(401, "Please log in to continue.")
        g.user = user
        return view(*args, **kwargs)

    return wrapper


@bp.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    login_id = str(data.get("login", "")).strip().lower()
    password = str(data.get("password", ""))
    if not login_id or not password:
        raise ApiError(400, "Enter your username (or email) and password.")

    user = query_one(
        "SELECT id, username, email, password_hash, is_creator, is_approver "
        "FROM users WHERE lower(username) = %s OR lower(email) = %s",
        (login_id, login_id),
    )
    hashed = user["password_hash"] if user else _get_dummy_hash()
    if not check_password(password, hashed) or user is None:
        current_app.logger.info("login failed for %r", login_id)
        raise ApiError(401, "Wrong username/email or password.")

    session.clear()  # fresh session on login (prevents session fixation)
    session.permanent = True
    session["user_id"] = user["id"]
    g.user = user
    current_app.logger.info("login ok user=%s", user["username"])
    return jsonify({"user": public_user(user)})


@bp.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@bp.get("/api/me")
@login_required
def me():
    return jsonify({"user": public_user(g.user)})
