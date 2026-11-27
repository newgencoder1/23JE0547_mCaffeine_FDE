"""Replay every distinct SQL statement the app ran during the test suite through
REAL Postgres's planner (EXPLAIN, so nothing is executed). Catches Postgres-only
syntax, wrong column names and type mismatches that SQLite would let through.

    SQL_LOG=/tmp/sql.jsonl python -m pytest -q
    python tests/pg_explain.py /tmp/sql.jsonl "postgresql://..."
"""
import json
import subprocess
import sys


def literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def main(log_path, dsn):
    seen = {}
    with open(log_path, encoding="utf-8") as fh:
        for line in fh:
            entry = json.loads(line)
            seen.setdefault(entry["sql"], entry["params"])
    failures = 0
    for sql, params in seen.items():
        parts = sql.split("%s")
        filled = parts[0] + "".join(literal(p) + rest for p, rest in zip(params, parts[1:]))
        proc = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-qtAX", "-c", "EXPLAIN " + filled],
                              capture_output=True, text=True)
        ok = proc.returncode == 0
        failures += not ok
        print(("OK   " if ok else "FAIL ") + " ".join(sql.split())[:110])
        if not ok:
            print("     ", proc.stderr.strip())
    print(f"\n{len(seen) - failures}/{len(seen)} statements accepted by Postgres")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
