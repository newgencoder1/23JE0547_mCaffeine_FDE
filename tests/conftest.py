"""Test harness.

The app talks to Postgres in production. For fast, self-contained tests we plug in
an SQLite connection that understands the same SQL (placeholders and now() are
translated below) and an in-memory fake for object storage. The schema-level
guarantees (UNIQUE, CHECK, append-only trigger) are mirrored in schema_sqlite.sql,
and db/schema.sql itself is verified against real Postgres by tests/pg_verify.sh.
"""
import hashlib
import json
import os
import sqlite3
import sys
import types
from datetime import datetime, timezone
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

# bcrypt is a compiled package; if it isn't installed in the test environment,
# use a stand-in with the same interface (production always uses real bcrypt).
try:
    import bcrypt  # noqa: F401
except ImportError:
    fake = types.ModuleType("bcrypt")
    fake.gensalt = lambda rounds=12: os.urandom(8).hex().encode()
    fake.hashpw = lambda pw, salt: b"fake$" + salt + b"$" + hashlib.sha256(salt + pw).hexdigest().encode()

    def _checkpw(pw, hashed):
        try:
            _, salt, digest = hashed.split(b"$")
        except ValueError:
            raise ValueError("Invalid salt") from None
        return hashlib.sha256(salt + pw).hexdigest().encode() == digest

    fake.checkpw = _checkpw
    sys.modules["bcrypt"] = fake

from app import create_app  # noqa: E402
from app.auth import hash_password  # noqa: E402

PASSWORD = "Test-Password-1"
SQL_LOG = os.environ.get("SQL_LOG")  # if set, every statement is recorded for tests/pg_explain.py
sqlite3.register_adapter(Decimal, str)


class _UniqueViolation(Exception):
    sqlstate = "23505"


class _Cursor:
    def __init__(self, cur):
        self._cur = cur

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._cur.close()

    def execute(self, sql, params=()):
        if SQL_LOG:
            with open(SQL_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"sql": sql, "params": [p if isinstance(p, (int, type(None))) else str(p) for p in params]}) + "\n")
        sql = sql.replace("%s", "?").replace(" FOR UPDATE", "")
        params = tuple(p.isoformat() if hasattr(p, "isoformat") else p for p in params)
        try:
            self._cur.execute(sql, params)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise _UniqueViolation(str(exc)) from None
            raise

    def fetchone(self):
        row = self._cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        return [dict(r) for r in self._cur.fetchall()]

    @property
    def rowcount(self):
        return self._cur.rowcount


class SqliteConn:
    def __init__(self, path):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.create_function(
            "now", 0, lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
        )

    def cursor(self):
        return _Cursor(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


class BrokenConn:
    def __init__(self):
        raise ConnectionError("database unreachable")


class FakeStorage:
    def __init__(self):
        self.objects = {}

    def upload_pdf(self, key, data):
        self.objects[key] = data

    def signed_url(self, key):
        return f"https://storage.test/signed/{key}?token=abc"

    def delete(self, key):
        self.objects.pop(key, None)

    def ping(self):
        return True


class TestConfig:
    DATABASE_URL = "sqlite://test"
    SECRET_KEY = "test-secret"
    SUPABASE_URL = "https://storage.test"
    SUPABASE_SERVICE_ROLE_KEY = "x"
    STORAGE_BUCKET = "po-pdfs"
    OCR_ENABLED = False
    SESSION_COOKIE_SECURE = False
    LOG_LEVEL = "INFO"
    APP_VERSION = "test"

    def missing(self):
        return []


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    with open(os.path.join(ROOT, "tests", "schema_sqlite.sql"), encoding="utf-8") as fh:
        conn.executescript(fh.read())
    for username, creator, approver in (
        ("creator1", 1, 0), ("creator2", 1, 0), ("approver1", 0, 1), ("lead1", 1, 1),
    ):
        conn.execute(
            "INSERT INTO users (username, email, password_hash, is_creator, is_approver) VALUES (?, ?, ?, ?, ?)",
            (username, f"{username}@example.com", hash_password(PASSWORD), creator, approver),
        )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def storage():
    return FakeStorage()


@pytest.fixture
def app(db_path, storage):
    application = create_app(config=TestConfig(), db_connect=lambda: SqliteConn(db_path), storage=storage)
    application.config["TESTING"] = False  # exercise the real error handlers
    return application


@pytest.fixture
def client_for(app):
    """client_for('creator1') -> a test client already logged in as that user."""

    def make(username=None):
        client = app.test_client()
        if username:
            res = client.post("/api/login", json={"login": username, "password": PASSWORD})
            assert res.status_code == 200, res.get_json()
        return client

    return make


def sample_path(name):
    """Prefer the real sample from the brief (samples/<name>), else our generated look-alike."""
    for folder in ("samples", os.path.join("samples", "generated")):
        path = os.path.join(ROOT, folder, name)
        if os.path.exists(path):
            return path
    pytest.skip(f"{name} not found")


def upload(client, name):
    with open(sample_path(name), "rb") as fh:
        return client.post("/api/pos/upload", data={"file": (fh, name)}, content_type="multipart/form-data")


@pytest.fixture
def broken_app(storage):
    return create_app(config=TestConfig(), db_connect=BrokenConn, storage=storage)

