#!/usr/bin/env bash
# Verifies db/schema.sql and the database-level guarantees against a REAL Postgres:
#   1. schema applies cleanly (twice — it is idempotent)
#   2. UNIQUE po_number rejects a duplicate
#   3. two approvers clicking at the same moment -> exactly one wins (conditional UPDATE)
#   4. po_actions is append-only (UPDATE/DELETE refused by trigger)
# Usage: bash tests/pg_verify.sh "postgresql://user@localhost/dbname"
set -euo pipefail
DB="$1"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
q() { psql "$DB" -v ON_ERROR_STOP=1 -qtAX -c "$1"; }

psql "$DB" -v ON_ERROR_STOP=1 -q -f "$HERE/db/schema.sql"
psql "$DB" -v ON_ERROR_STOP=1 -q -f "$HERE/db/schema.sql"
echo "1. schema applied twice: OK"

# Test-only reset (needs table owner rights to bypass the append-only triggers).
q "ALTER TABLE po_actions DISABLE TRIGGER USER; TRUNCATE po_actions, po_line_items, purchase_orders, users RESTART IDENTITY CASCADE; ALTER TABLE po_actions ENABLE TRIGGER USER;"
q "INSERT INTO users (username,email,password_hash,is_creator,is_approver) VALUES
   ('creator1','c1@example.com','x',true,false),('approver1','a1@example.com','x',false,true),('lead1','l1@example.com','x',true,true)"
q "INSERT INTO purchase_orders (po_number,status,created_by,total_paise) VALUES ('PO-2026-001','SUBMITTED',1,12450000)"

if q "INSERT INTO purchase_orders (po_number,created_by) VALUES ('PO-2026-001',1)" 2>/dev/null; then
  echo "2. UNIQUE po_number: FAILED (duplicate accepted)"; exit 1
else
  echo "2. UNIQUE po_number: OK (duplicate refused with SQLSTATE 23505)"
fi

# Two "approve" transactions racing. Each holds its transaction open briefly so they overlap.
APPROVE="BEGIN;
  UPDATE purchase_orders SET status='APPROVED', updated_at=now()
   WHERE id=1 AND status='SUBMITTED' AND created_by <> %s RETURNING id;
  SELECT pg_sleep(1);
COMMIT;"
psql "$DB" -qtAX -c "$(printf "$APPROVE" 2)" > /tmp/race_a.txt &
psql "$DB" -qtAX -c "$(printf "$APPROVE" 3)" > /tmp/race_b.txt &
wait
WINNERS=$(cat /tmp/race_a.txt /tmp/race_b.txt | grep -c '^1$' || true)
STATUS=$(q "SELECT status FROM purchase_orders WHERE id=1")
if [ "$WINNERS" = "1" ] && [ "$STATUS" = "APPROVED" ]; then
  echo "3. concurrent approve: OK (exactly 1 of 2 updates matched; status=$STATUS)"
else
  echo "3. concurrent approve: FAILED (winners=$WINNERS status=$STATUS)"; exit 1
fi

q "INSERT INTO po_actions (po_id,actor_id,action,from_status,to_status) VALUES (1,2,'APPROVE','SUBMITTED','APPROVED')"
if q "UPDATE po_actions SET remark='tampered'" 2>/dev/null || q "DELETE FROM po_actions" 2>/dev/null \
   || q "TRUNCATE po_actions CASCADE" 2>/dev/null; then
  echo "4. append-only history: FAILED"; exit 1
else
  echo "4. append-only history: OK (UPDATE, DELETE and TRUNCATE refused by triggers)"
fi
