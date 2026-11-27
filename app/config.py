"""All configuration comes from environment variables (see .env.example).

Nothing secret is hard-coded. Missing values are reported by /health instead of
crashing the process, so a misconfigured deploy is easy to diagnose.
"""
import os


def _bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class Config:
    def __init__(self):
        self.DATABASE_URL = os.environ.get("DATABASE_URL", "")
        self.SECRET_KEY = os.environ.get("SECRET_KEY", "")
        self.SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self.SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        self.STORAGE_BUCKET = os.environ.get("STORAGE_BUCKET", "po-pdfs")
        self.OCR_ENABLED = _bool("OCR_ENABLED", False)
        self.SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", True)
        self.LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
        # Render sets RENDER_GIT_COMMIT automatically; shown by /health so you
        # can tell which build is live.
        self.APP_VERSION = os.environ.get("RENDER_GIT_COMMIT", "local")[:7]

    def missing(self):
        """Names (never values) of required settings that are not set."""
        required = ["DATABASE_URL", "SECRET_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
        return [name for name in required if not getattr(self, name)]


MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB, per the brief
