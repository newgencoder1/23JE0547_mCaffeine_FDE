"""Every authorization rule in one place, so each one is easy to find and defend.

Rule numbers match section 3 of the brief:
  1. no valid login                         -> 401   (auth.login_required)
  2. only Approvers approve/reject          -> 403   require_approver()
  3. nobody decides a PO they created       -> 403   require_not_own_po()
  4. creators see/edit/submit only their own POs; someone else's PO by id -> 404
                                                     load_visible_po(), require_owner()
     edit only while DRAFT or REJECTED      -> 409   require_editable()
  5. only SUBMITTED can be decided; 2nd approve -> 409  (workflow.py, atomic UPDATE)
  6. rejection needs a non-empty reason     -> 400   (workflow.py)
  7. approvers see SUBMITTED POs of all creators, never edit contents
                                                     load_visible_po(), require_owner()

Why 404 (not 403) for someone else's PO: a 403 would confirm that PO id exists
and belongs to somebody else. 404 reveals nothing, which matches how we treat
duplicate PO numbers (we say "already exists", never whose it is).
"""
from .db import query_one
from .errors import ApiError

EDITABLE_STATUSES = ("DRAFT", "REJECTED")


def can_view(user, po):
    if po["created_by"] == user["id"]:
        return True
    # Approvers may open any PO that has left DRAFT (the queue, plus decided POs
    # so they can see their own decisions). Drafts stay private to their creator.
    return bool(user["is_approver"]) and po["status"] != "DRAFT"


def load_visible_po(user, po_id, for_update=False):
    """Return the PO row if this user may see it; otherwise 404 (also when it doesn't exist)."""
    sql = "SELECT * FROM purchase_orders WHERE id = %s"
    if for_update:
        sql += " FOR UPDATE"  # lock the row for the rest of the transaction
    po = query_one(sql, (po_id,))
    if po is None or not can_view(user, po):
        raise ApiError(404, "Purchase order not found.")
    return po


def require_creator_role(user):
    if not user["is_creator"]:
        raise ApiError(403, "Only users with the Creator role can create purchase orders.")


def require_approver(user):
    if not user["is_approver"]:
        raise ApiError(403, "Only Approvers can approve or reject purchase orders.")


def require_not_own_po(user, po):
    if po["created_by"] == user["id"]:
        raise ApiError(403, "You cannot approve or reject a purchase order you created.")


def require_owner(user, po):
    """Only the PO's creator may edit, submit or discard it (approvers never edit contents)."""
    if po["created_by"] != user["id"]:
        raise ApiError(403, "Only the creator of this purchase order can change it.")


def require_editable(po):
    if po["status"] not in EDITABLE_STATUSES:
        raise ApiError(
            409,
            f"This purchase order is {po['status']} and locked. "
            "It can only be edited while DRAFT or REJECTED.",
        )
