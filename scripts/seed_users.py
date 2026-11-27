"""Create the tables (optional) and the four test users.

    python scripts/seed_users.py --schema     # first run: create tables + users
    python scripts/seed_users.py              # re-run: reset the users' password/roles

Reads DATABASE_URL and SEED_PASSWORD from the environment (or .env). The password
is never written in code. Safe to run repeatedly (upsert by username).
"""
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

from app.auth import hash_password  # noqa: E402

USERS = [
    # username,   email,                    is_creator, is_approver
    ("creator1", "creator1@example.com", True, False),
    ("creator2", "creator2@example.com", True, False),
    ("approver1", "approver1@example.com", False, True),
    ("lead1", "lead1@example.com", True, True),
]


def main():
    import psycopg

    url, password = os.environ.get("DATABASE_URL"), os.environ.get("SEED_PASSWORD")
    if not url or not password:
        sys.exit("Set DATABASE_URL and SEED_PASSWORD first (see .env.example).")
    if len(password) < 8:
        sys.exit("SEED_PASSWORD must be at least 8 characters.")

    with psycopg.connect(url, prepare_threshold=None) as conn:
        if "--schema" in sys.argv:
            schema = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")
            with open(schema, encoding="utf-8") as fh:
                conn.execute(fh.read())
            print("schema applied")
        for username, email, is_creator, is_approver in USERS:
            conn.execute(
                "INSERT INTO users (username, email, password_hash, is_creator, is_approver) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (username) DO UPDATE SET email = EXCLUDED.email, "
                "password_hash = EXCLUDED.password_hash, is_creator = EXCLUDED.is_creator, "
                "is_approver = EXCLUDED.is_approver",
                (username, email, hash_password(password), is_creator, is_approver),
            )
            roles = " + ".join(r for r, on in (("Creator", is_creator), ("Approver", is_approver)) if on)
            print(f"  {username:<10} {roles}")
        conn.commit()
    print("done")


if __name__ == "__main__":
    main()
