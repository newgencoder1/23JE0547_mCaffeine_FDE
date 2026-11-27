"""Application factory: wires config, logging, error handling and routes together."""
import logging
import sys
import time
import uuid
from datetime import timedelta

from flask import Flask, g, request

from .config import MAX_UPLOAD_BYTES, Config
from .db import close_db, postgres_connect
from .errors import register_error_handlers


class _RequestIdFilter(logging.Filter):
    """Adds the current request id (or '-') to every log line."""

    def filter(self, record):
        try:
            record.request_id = g.get("request_id", "-")
        except RuntimeError:  # outside a request (startup, scripts)
            record.request_id = "-"
        return True


def _configure_logging(app, level):
    handler = logging.StreamHandler(sys.stdout)  # hosts collect stdout into their log viewer
    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03dZ %(levelname)s [req=%(request_id)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime  # timestamps in UTC
    handler.setFormatter(formatter)
    handler.addFilter(_RequestIdFilter())
    app.logger.handlers = [handler]
    app.logger.setLevel(level)
    app.logger.propagate = False


def create_app(config=None, db_connect=None, storage=None):
    cfg = config or Config()
    app = Flask(__name__, static_folder="static", static_url_path="/static")

    app.config.update(
        APP_CONFIG=cfg,
        SECRET_KEY=cfg.SECRET_KEY or None,
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES + 64 * 1024,  # small allowance for form overhead
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=cfg.SESSION_COOKIE_SECURE,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        DB_CONNECT=db_connect or (lambda: postgres_connect(cfg.DATABASE_URL)),
    )

    if storage is None:
        from .storage import SupabaseStorage

        storage = SupabaseStorage(cfg.SUPABASE_URL, cfg.SUPABASE_SERVICE_ROLE_KEY, cfg.STORAGE_BUCKET)
    app.extensions["storage"] = storage

    _configure_logging(app, cfg.LOG_LEVEL)
    if cfg.missing():
        app.logger.error("missing required environment variables: %s", ", ".join(cfg.missing()))

    @app.before_request
    def _start_request():
        g.request_id = uuid.uuid4().hex[:12]
        g.started = time.perf_counter()

    @app.after_request
    def _finish_request(response):
        elapsed_ms = (time.perf_counter() - g.get("started", time.perf_counter())) * 1000
        user = g.get("user")
        if not request.path.startswith("/static"):
            app.logger.info(
                "%s %s -> %s %.0fms user=%s",
                request.method,
                request.path,
                response.status_code,
                elapsed_ms,
                user["username"] if user else "-",
            )
        response.headers["X-Request-ID"] = g.get("request_id", "-")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    app.teardown_appcontext(close_db)
    register_error_handlers(app)

    from .auth import bp as auth_bp
    from .health import bp as health_bp
    from .pages import bp as pages_bp
    from .pos import bp as pos_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(pos_bp)
    app.register_blueprint(pages_bp)
    return app
