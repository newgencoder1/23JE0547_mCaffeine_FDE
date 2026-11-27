"""The PO state machine. Every status change goes through `_transition`, which:

  1. performs a CONDITIONAL update (… WHERE id = ? AND status = <expected>), so the
     change happens at most once even if two requests arrive at the same moment;
  2. writes exactly one append-only history row in the SAME transaction, so a
     status change without a history entry (or vice versa) is impossible.

Allowed transitions (anything else is refused):

    DRAFT     --SUBMIT-->   SUBMITTED   by the PO's creator
    REJECTED  --RESUBMIT--> SUBMITTED   by the PO's creator (same PO, edited)
    SUBMITTED --APPROVE-->  APPROVED    by an Approver who is not the creator (final)
    SUBMITTED --REJECT-->   REJECTED    by an Approver who is not the creator, reason required
"""
from decimal import Decimal

from flask import current_app

from . import permissions as perm
from .db import execute, query_all, query_one, transaction
from .errors import ApiError
from .validation import run_checks

TRANSITIONS = {
    ("DRAFT", "SUBMIT"): "SUBMITTED",
    ("REJECTED", "RESUBMIT"): "SUBMITTED",
    ("SUBMITTED", "APPROVE"): "APPROVED",
    ("SUBMITTED", "REJECT"): "REJECTED",
}


def _transition(po, user, action, remark=None, extra_where="", extra_params=()):
    from_status = po["status"]
    to_status = TRANSITIONS.get((from_status, action))
    if to_status is None:
        raise ApiError(409, f"Cannot {action.lower()} a purchase order that is {from_status}.")

    # The WHERE clause is the real guard: if another request changed the status a
    # millisecond ago, this matches 0 rows and we refuse instead of double-applying.
    row = query_one(
        "UPDATE purchase_orders SET status = %s, updated_at = now() "
        "WHERE id = %s AND status = %s" + extra_where + " RETURNING id",
        (to_status, po["id"], from_status, *extra_params),
    )
    if row is None:
        raise ApiError(409, "This purchase order was changed by someone else just now. Refresh and try again.")

    execute(
        "INSERT INTO po_actions (po_id, actor_id, action, from_status, to_status, remark) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (po["id"], user["id"], action, from_status, to_status, remark),
    )
    current_app.logger.info(
        "transition po=%s %s %s->%s by=%s", po["id"], action, from_status, to_status, user["username"]
    )
    return to_status


def load_lines(po_id):
    return query_all(
        "SELECT line_no, sku, description, quantity, unit_price_paise, line_total_paise "
        "FROM po_line_items WHERE po_id = %s ORDER BY line_no",
        (po_id,),
    )


def submit(user, po_id):
    with transaction():
        po = perm.load_visible_po(user, po_id, for_update=True)
        perm.require_owner(user, po)
        if po["status"] not in perm.EDITABLE_STATUSES:
            raise ApiError(409, f"This purchase order is already {po['status']}.")

        # Checks run again on the server from what is stored — whatever the browser sent.
        checks = run_checks(po, [_line_for_checks(l) for l in load_lines(po_id)])
        if not checks["ok"]:
            raise ApiError(422, "Fix the highlighted problems before submitting.", extra={"checks": checks})

        action = "SUBMIT" if po["status"] == "DRAFT" else "RESUBMIT"
        return _transition(po, user, action, extra_where=" AND created_by = %s", extra_params=(user["id"],))


def approve(user, po_id, remark=None):
    perm.require_approver(user)                      # rule 2 (checked before we even look up the PO)
    with transaction():
        po = perm.load_visible_po(user, po_id)       # rule 4/7: 404 if not visible
        perm.require_not_own_po(user, po)            # rule 3
        if po["status"] != "SUBMITTED":              # rule 5
            raise ApiError(409, f"Only SUBMITTED purchase orders can be approved; this one is {po['status']}.")
        remark = (remark or "").strip() or None
        return _transition(
            po, user, "APPROVE", remark, extra_where=" AND created_by <> %s", extra_params=(user["id"],)
        )


def reject(user, po_id, reason):
    perm.require_approver(user)                      # rule 2
    with transaction():
        po = perm.load_visible_po(user, po_id)
        perm.require_not_own_po(user, po)            # rule 3
        if po["status"] != "SUBMITTED":              # rule 5
            raise ApiError(409, f"Only SUBMITTED purchase orders can be rejected; this one is {po['status']}.")
        reason = (reason or "").strip()
        if not reason:                               # rule 6
            raise ApiError(400, "A reason is required to reject a purchase order.", fields={"reason": "Required."})
        return _transition(
            po, user, "REJECT", reason, extra_where=" AND created_by <> %s", extra_params=(user["id"],)
        )


def _line_for_checks(row):
    return {
        "sku": row["sku"],
        "description": row["description"],
        "quantity": Decimal(str(row["quantity"])) if row["quantity"] is not None else None,
        "unit_price_paise": row["unit_price_paise"],
        "line_total_paise": row["line_total_paise"],
    }
