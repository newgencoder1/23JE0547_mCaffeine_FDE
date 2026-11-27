"""Database access: one connection per request, closed when the request ends.

Production uses psycopg 3 against Supabase Postgres. Tests swap in a different
connection factory via app.config["DB_CONNECT"], so nothing here is tied to a
real server during testing.
"""
from contextlib import contextmanager

from flask import current_app, g


def postgres_connect(database_url):
    import psycopg
    from psycopg.rows import dict_row

    # connect_timeout keeps /health fast when the database is down.
    # prepare_threshold=None keeps us compatible with Supabase's pooler.
    return psycopg.connect(
        database_url,
        row_factory=dict_row,
        connect_timeout=5,
        prepare_threshold=None,
    )


def get_db():
    if "db" not in g:
        connect = current_app.config["DB_CONNECT"]
        g.db = connect()
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:  # closing a broken connection must never mask the real error
            current_app.logger.warning("failed to close db connection")


def query_one(sql, params=()):
    with get_db().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def query_all(sql, params=()):
    with get_db().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@contextmanager
def transaction():
    """Run a block as one all-or-nothing transaction (commit on success, else roll back)."""
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def is_unique_violation(exc):
    """True if the exception is a UNIQUE-constraint violation (SQLSTATE 23505)."""
    return getattr(exc, "sqlstate", None) == "23505"
