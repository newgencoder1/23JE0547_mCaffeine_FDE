"""GET /health — OK only when the app is running AND can reach the database.

  200 {"status": "ok", ...}      app up, database answered SELECT 1
  503 {"status": "error", ...}   database unreachable or not configured

/health?deep=1 additionally checks that the PDF storage bucket answers. It never
returns secret values, only whether each setting is present.
"""
from flask import Blueprint, current_app, jsonify, request

from .db import query_one

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    cfg = current_app.config["APP_CONFIG"]
    body = {
        "status": "ok",
        "version": cfg.APP_VERSION,
        "checks": {},
        "missing_config": cfg.missing(),
    }

    try:
        row = query_one("SELECT 1 AS ok")
        body["checks"]["database"] = "ok" if row and row["ok"] == 1 else "unexpected reply"
    except Exception as exc:  # any failure to reach the DB means "not healthy"
        current_app.logger.error("health: database unreachable: %s", type(exc).__name__)
        body["checks"]["database"] = "unreachable"

    if request.args.get("deep") == "1":
        ok = current_app.extensions["storage"].ping()
        body["checks"]["storage"] = "ok" if ok else "unreachable"

    healthy = all(v == "ok" for v in body["checks"].values())
    if not healthy:
        body["status"] = "error"
    return jsonify(body), (200 if healthy else 503)
