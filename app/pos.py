"""Purchase-order API. Every route starts with @login_required (rule 1) and then
calls the named checks from permissions.py / workflow.py before touching data.

  GET    /api/pos?view=mine|queue|decided   list
  POST   /api/pos/upload                    upload PDF -> new DRAFT (creator role)
  GET    /api/pos/<id>                      details + line items + history + checks
  PUT    /api/pos/<id>                      edit (owner, DRAFT/REJECTED only)
  POST   /api/pos/<id>/submit               DRAFT/REJECTED -> SUBMITTED (owner)
  POST   /api/pos/<id>/approve              SUBMITTED -> APPROVED (approver, not creator)
  POST   /api/pos/<id>/reject               SUBMITTED -> REJECTED (approver, not creator, reason)
  GET    /api/pos/<id>/pdf                  redirect to a 5-minute signed link to the original
  DELETE /api/pos/<id>                      discard a DRAFT that was never submitted (owner)

There is deliberately no route that edits or deletes history (po_actions).
"""
import uuid
from datetime import datetime

from flask import Blueprint, current_app, g, jsonify, redirect, request

from . import permissions as perm
from . import workflow
from .auth import login_required
from .config import MAX_UPLOAD_BYTES
from .db import execute, is_unique_violation, query_all, query_one, transaction
from .errors import ApiError
from .extraction import extract_po
from .validation import (
    normalize_po_number,
    paise_to_str,
    parse_date,
    parse_money,
    parse_quantity,
    run_checks,
    to_iso,
)

bp = Blueprint("pos", __name__)

DUPLICATE_MESSAGE = "PO number {} already exists. Each PO number can be entered only once."


# ------------------------------------------------------------------ helpers
def _ts(value):
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _history(po_id):
    rows = query_all(
        "SELECT a.id, a.action, a.from_status, a.to_status, a.remark, a.created_at, u.username "
        "FROM po_actions a JOIN users u ON u.id = a.actor_id WHERE a.po_id = %s ORDER BY a.id",
        (po_id,),
    )
    return [
        {
            "id": r["id"],
            "action": r["action"],
            "from_status": r["from_status"],
            "to_status": r["to_status"],
            "remark": r["remark"],
            "by": r["username"],
            "at": _ts(r["created_at"]),
        }
        for r in rows
    ]


def _serialize(po, user, include_details=True):
    creator = query_one("SELECT username FROM users WHERE id = %s", (po["created_by"],))
    out = {
        "id": po["id"],
        "po_number": po["po_number"],
        "po_date": to_iso(po["po_date"]),
        "vendor_name": po["vendor_name"],
        "total_paise": po["total_paise"],
        "total": paise_to_str(po["total_paise"]) if po["total_paise"] is not None else None,
        "status": po["status"],
        "created_by": creator["username"] if creator else None,
        "is_own": po["created_by"] == user["id"],
        "extraction_method": po["extraction_method"],
        "extraction_note": po["extraction_note"],
        "has_pdf": bool(po["pdf_object_key"]),
        "pdf_filename": po["pdf_filename"],
        "created_at": _ts(po["created_at"]),
        "updated_at": _ts(po["updated_at"]),
    }
    if not include_details:
        return out

    rows = workflow.load_lines(po["id"])
    lines = [workflow._line_for_checks(r) for r in rows]
    out["line_items"] = [
        {
            "sku": l["sku"],
            "description": l["description"],
            "quantity": None if l["quantity"] is None else _qty_str(l["quantity"]),
            "unit_price": paise_to_str(l["unit_price_paise"]) if l["unit_price_paise"] is not None else None,
            "line_total": paise_to_str(l["line_total_paise"]) if l["line_total_paise"] is not None else None,
        }
        for l in lines
    ]
    out["checks"] = run_checks(po, lines)
    out["history"] = _history(po["id"])
    is_owner = po["created_by"] == user["id"]
    # These flags only decide which buttons the UI shows. The server re-checks
    # every rule on every request, so a crafted request gains nothing.
    out["permissions"] = {
        "can_edit": is_owner and po["status"] in perm.EDITABLE_STATUSES,
        "can_submit": is_owner and po["status"] in perm.EDITABLE_STATUSES,
        "can_decide": bool(user["is_approver"]) and not is_owner and po["status"] == "SUBMITTED",
        "can_discard": is_owner and po["status"] == "DRAFT",
    }
    return out


def _qty_str(qty):
    text = format(qty.normalize(), "f")
    return text


def _blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _parse_edit_payload(data):
    """Turn what the browser typed into typed values. Unparseable values -> 422, nothing saved."""
    errors, line_errors = {}, {}
    header = {
        "po_number": normalize_po_number(data.get("po_number")) if not _blank(data.get("po_number")) else None,
        "vendor_name": (data.get("vendor_name") or "").strip() or None,
        "po_date": None,
        "total_paise": None,
    }
    if not _blank(data.get("po_date")):
        try:
            header["po_date"] = parse_date(data["po_date"])
        except ValueError:
            errors["po_date"] = "Use a date like 15-11-2026."
    if not _blank(data.get("total")):
        try:
            header["total_paise"] = parse_money(data["total"])
        except ValueError:
            errors["total"] = "Enter an amount like 1,24,500.00."

    lines = []
    raw_lines = data.get("line_items") or []
    if not isinstance(raw_lines, list):
        raise ApiError(400, "line_items must be a list.")
    for i, raw in enumerate(raw_lines):
        raw = raw or {}
        if all(_blank(raw.get(k)) for k in ("sku", "description", "quantity", "unit_price", "line_total")):
            continue  # ignore completely empty rows
        e, line = {}, {
            "sku": (str(raw.get("sku") or "")).strip() or None,
            "description": (str(raw.get("description") or "")).strip() or None,
            "quantity": None,
            "unit_price_paise": None,
            "line_total_paise": None,
        }
        for field, key, parser in (
            ("quantity", "quantity", parse_quantity),
            ("unit_price", "unit_price_paise", parse_money),
            ("line_total", "line_total_paise", parse_money),
        ):
            if not _blank(raw.get(field)):
                try:
                    line[key] = parser(raw[field])
                except ValueError:
                    e[field] = "Not a valid number."
        if e:
            line_errors[str(i)] = e
        lines.append(line)

    if errors or line_errors:
        raise ApiError(
            422,
            "Some values could not be read. Fix the highlighted fields.",
            fields=errors,
            extra={"line_errors": line_errors},
        )
    return header, lines


def _insert_lines(po_id, lines):
    for n, line in enumerate(lines, start=1):
        execute(
            "INSERT INTO po_line_items (po_id, line_no, sku, description, quantity, unit_price_paise, "
            "line_total_paise) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                po_id, n, line["sku"], line["description"],
                None if line["quantity"] is None else str(line["quantity"]),
                line["unit_price_paise"], line["line_total_paise"],
            ),
        )


# ------------------------------------------------------------------ routes
@bp.get("/api/pos")
@login_required
def list_pos():
    user = g.user
    view = request.args.get("view", "mine")
    if view == "mine":
        rows = query_all(
            "SELECT * FROM purchase_orders WHERE created_by = %s ORDER BY updated_at DESC, id DESC",
            (user["id"],),
        )
    elif view in ("queue", "decided"):
        perm.require_approver(user)
        statuses = ("SUBMITTED",) if view == "queue" else ("APPROVED", "REJECTED")
        placeholders = ", ".join(["%s"] * len(statuses))
        rows = query_all(
            f"SELECT * FROM purchase_orders WHERE status IN ({placeholders}) ORDER BY updated_at DESC, id DESC",
            statuses,
        )
    else:
        raise ApiError(400, "view must be one of: mine, queue, decided.")
    return jsonify({"items": [_serialize(r, user, include_details=False) for r in rows]})


@bp.get("/api/pos/<int:po_id>")
@login_required
def get_po(po_id):
    po = perm.load_visible_po(g.user, po_id)
    return jsonify({"po": _serialize(po, g.user)})


@bp.post("/api/pos/upload")
@login_required
def upload_po():
    user = g.user
    perm.require_creator_role(user)

    file = request.files.get("file")
    if file is None or not file.filename:
        raise ApiError(400, "Choose a PDF file to upload.")
    data = file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "That file is larger than 5 MB. Please upload a smaller PDF.")
    if not data.startswith(b"%PDF-"):
        raise ApiError(400, "That file is not a PDF.")
    filename = file.filename[-200:]

    # 1) Store the original first, in the private bucket (never on this server's disk).
    key = f"pos/{uuid.uuid4().hex}.pdf"
    storage = current_app.extensions["storage"]
    try:
        storage.upload_pdf(key, data)
    except Exception as exc:  # StorageError or a network error
        current_app.logger.error("pdf upload to storage failed: %s", exc)
        raise ApiError(502, "We could not store the PDF right now. Please try again in a minute.") from None

    # 2) Read it. Never raises for a bad PDF: unreadable files come back with readable=False.
    result = extract_po(data, ocr_enabled=current_app.config["APP_CONFIG"].OCR_ENABLED)
    current_app.logger.info(
        "extraction file=%r method=%s readable=%s lines=%d", filename, result["method"], result["readable"],
        len(result["lines"]),
    )
    fields = result["fields"]

    # 3) Save as a DRAFT. If the PO number already exists, the UNIQUE constraint
    #    refuses it; we then save the draft without a number and tell the user.
    duplicate_of = None
    try:
        po_id = _create_draft(user, fields, result, key, filename, fields.get("po_number"))
    except Exception as exc:
        if not is_unique_violation(exc):
            storage.delete(key)
            raise
        duplicate_of = fields.get("po_number")
        po_id = _create_draft(user, fields, result, key, filename, None)

    po = query_one("SELECT * FROM purchase_orders WHERE id = %s", (po_id,))
    body = {
        "po": _serialize(po, user),
        "extraction": {
            "readable": result["readable"],
            "method": result["method"],
            "message": result["message"],
            "warnings": result["warnings"],
        },
    }
    if duplicate_of:
        body["duplicate"] = {"po_number": duplicate_of, "message": DUPLICATE_MESSAGE.format(duplicate_of)}
    return jsonify(body), 201


def _create_draft(user, fields, result, key, filename, po_number):
    with transaction():
        row = query_one(
            "INSERT INTO purchase_orders (po_number, po_date, vendor_name, total_paise, status, created_by, "
            "pdf_object_key, pdf_filename, extraction_method, extraction_note) "
            "VALUES (%s, %s, %s, %s, 'DRAFT', %s, %s, %s, %s, %s) RETURNING id",
            (
                po_number, fields.get("po_date"), fields.get("vendor_name"), fields.get("total_paise"),
                user["id"], key, filename, result["method"], result["message"],
            ),
        )
        _insert_lines(row["id"], result["lines"])
        return row["id"]


@bp.put("/api/pos/<int:po_id>")
@login_required
def update_po(po_id):
    user = g.user
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "Send the PO fields as JSON.")
    header, lines = _parse_edit_payload(data)
    try:
        with transaction():
            po = perm.load_visible_po(user, po_id, for_update=True)
            perm.require_owner(user, po)        # approvers never edit contents (rule 7)
            perm.require_editable(po)           # locked unless DRAFT or REJECTED (rule 4)
            execute(
                "UPDATE purchase_orders SET po_number = %s, po_date = %s, vendor_name = %s, total_paise = %s, "
                "updated_at = now() WHERE id = %s AND status IN ('DRAFT', 'REJECTED')",
                (header["po_number"], header["po_date"], header["vendor_name"], header["total_paise"], po_id),
            )
            execute("DELETE FROM po_line_items WHERE po_id = %s", (po_id,))
            _insert_lines(po_id, lines)
    except Exception as exc:
        if is_unique_violation(exc):
            # Check 5: says the number exists — never whose PO it is or what is in it.
            raise ApiError(
                409, DUPLICATE_MESSAGE.format(header["po_number"]),
                fields={"po_number": "This PO number already exists."},
            ) from None
        raise
    po = query_one("SELECT * FROM purchase_orders WHERE id = %s", (po_id,))
    return jsonify({"po": _serialize(po, user)})


@bp.post("/api/pos/<int:po_id>/submit")
@login_required
def submit_po(po_id):
    workflow.submit(g.user, po_id)
    return jsonify({"po": _serialize(perm.load_visible_po(g.user, po_id), g.user)})


@bp.post("/api/pos/<int:po_id>/approve")
@login_required
def approve_po(po_id):
    data = request.get_json(silent=True) or {}
    workflow.approve(g.user, po_id, data.get("remark"))
    return jsonify({"po": _serialize(perm.load_visible_po(g.user, po_id), g.user)})


@bp.post("/api/pos/<int:po_id>/reject")
@login_required
def reject_po(po_id):
    data = request.get_json(silent=True) or {}
    workflow.reject(g.user, po_id, data.get("reason"))
    return jsonify({"po": _serialize(perm.load_visible_po(g.user, po_id), g.user)})


@bp.get("/api/pos/<int:po_id>/pdf")
@login_required
def open_pdf(po_id):
    po = perm.load_visible_po(g.user, po_id)  # same visibility rule as the PO itself
    if not po["pdf_object_key"]:
        raise ApiError(404, "No PDF is attached to this purchase order.")
    try:
        url = current_app.extensions["storage"].signed_url(po["pdf_object_key"])
    except Exception as exc:
        current_app.logger.error("signing pdf url failed for po=%s: %s", po_id, exc)
        raise ApiError(502, "The PDF could not be opened right now. Please try again in a minute.") from None
    return redirect(url, code=302)


@bp.delete("/api/pos/<int:po_id>")
@login_required
def discard_draft(po_id):
    user = g.user
    with transaction():
        po = perm.load_visible_po(user, po_id, for_update=True)
        perm.require_owner(user, po)
        if po["status"] != "DRAFT":
            raise ApiError(409, "Only a DRAFT that was never submitted can be discarded.")
        execute("DELETE FROM po_line_items WHERE po_id = %s", (po_id,))
        execute("DELETE FROM purchase_orders WHERE id = %s AND status = 'DRAFT'", (po_id,))
    if po["pdf_object_key"]:
        current_app.extensions["storage"].delete(po["pdf_object_key"])
    current_app.logger.info("draft discarded po=%s by=%s", po_id, user["username"])
    return jsonify({"ok": True})
