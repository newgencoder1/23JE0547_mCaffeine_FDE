-- SQLite mirror of db/schema.sql, used only by the test suite.
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_creator INTEGER NOT NULL DEFAULT 0,
    is_approver INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_number TEXT UNIQUE,
    po_date TEXT,
    vendor_name TEXT,
    total_paise INTEGER CHECK (total_paise IS NULL OR total_paise >= 0),
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED')),
    created_by INTEGER NOT NULL REFERENCES users(id),
    pdf_object_key TEXT,
    pdf_filename TEXT,
    extraction_method TEXT NOT NULL DEFAULT 'manual' CHECK (extraction_method IN ('text_layer', 'ocr', 'manual')),
    extraction_note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE po_line_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    line_no INTEGER NOT NULL,
    sku TEXT, description TEXT, quantity TEXT,
    unit_price_paise INTEGER, line_total_paise INTEGER
);
CREATE TABLE po_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id INTEGER NOT NULL REFERENCES purchase_orders(id),
    actor_id INTEGER NOT NULL REFERENCES users(id),
    action TEXT NOT NULL CHECK (action IN ('SUBMIT', 'APPROVE', 'REJECT', 'RESUBMIT')),
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    remark TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER po_actions_no_update BEFORE UPDATE ON po_actions BEGIN SELECT RAISE(ABORT, 'po_actions is append-only'); END;
CREATE TRIGGER po_actions_no_delete BEFORE DELETE ON po_actions BEGIN SELECT RAISE(ABORT, 'po_actions is append-only'); END;
