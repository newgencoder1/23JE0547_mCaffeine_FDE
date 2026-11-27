-- PO Approval Tool — database schema (PostgreSQL / Supabase)
-- Run once in the Supabase SQL editor, or: psql "$DATABASE_URL" -f db/schema.sql
--
-- Design notes
--   * Money is stored as BIGINT paise (1 rupee = 100 paise). Never floats.
--   * Dates are DATE (ISO YYYY-MM-DD). The UI renders them as DD-MM-YYYY.
--   * po_number has a UNIQUE constraint in the database itself, so duplicates are
--     impossible even if two uploads race each other. NULL is allowed while a
--     draft has no number yet (Postgres treats NULLs as distinct).
--   * po_actions is append-only: the app has no UPDATE/DELETE path for it, and the
--     trigger below rejects any attempt at the database level as well.

CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,                 -- bcrypt hash
    is_creator    BOOLEAN NOT NULL DEFAULT FALSE,
    is_approver   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id                 BIGSERIAL PRIMARY KEY,
    po_number          TEXT UNIQUE,              -- the duplicate guard
    po_date            DATE,
    vendor_name        TEXT,
    total_paise        BIGINT CHECK (total_paise IS NULL OR total_paise >= 0),
    status             TEXT NOT NULL DEFAULT 'DRAFT'
                       CHECK (status IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED')),
    created_by         BIGINT NOT NULL REFERENCES users(id),
    pdf_object_key     TEXT,                     -- key inside the private storage bucket
    pdf_filename       TEXT,
    extraction_method  TEXT NOT NULL DEFAULT 'manual'
                       CHECK (extraction_method IN ('text_layer', 'ocr', 'manual')),
    extraction_note    TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_po_created_by ON purchase_orders (created_by);
CREATE INDEX IF NOT EXISTS idx_po_status     ON purchase_orders (status);

CREATE TABLE IF NOT EXISTS po_line_items (
    id                BIGSERIAL PRIMARY KEY,
    po_id             BIGINT NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    line_no           INTEGER NOT NULL,
    sku               TEXT,
    description       TEXT,
    quantity          NUMERIC(14, 3),
    unit_price_paise  BIGINT,
    line_total_paise  BIGINT
);

CREATE INDEX IF NOT EXISTS idx_line_items_po ON po_line_items (po_id);

CREATE TABLE IF NOT EXISTS po_actions (
    id          BIGSERIAL PRIMARY KEY,
    po_id       BIGINT NOT NULL REFERENCES purchase_orders(id),
    actor_id    BIGINT NOT NULL REFERENCES users(id),
    action      TEXT NOT NULL CHECK (action IN ('SUBMIT', 'APPROVE', 'REJECT', 'RESUBMIT')),
    from_status TEXT NOT NULL,
    to_status   TEXT NOT NULL,
    remark      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()   -- server (database) time
);

CREATE INDEX IF NOT EXISTS idx_actions_po ON po_actions (po_id, id);

-- Defence in depth: history rows can never be changed or removed.
CREATE OR REPLACE FUNCTION po_actions_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'po_actions is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_po_actions_append_only ON po_actions;
CREATE TRIGGER trg_po_actions_append_only
    BEFORE UPDATE OR DELETE ON po_actions
    FOR EACH ROW EXECUTE FUNCTION po_actions_append_only();
