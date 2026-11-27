"""End-to-end API tests of every rule in section 3, called the way curl/Postman would."""
import pytest

from tests.conftest import upload

GOOD_EDIT = {
    "po_number": "PO-T-100", "po_date": "15-11-2026", "vendor_name": "ABC Industries", "total": "₹1,24,500.00",
    "line_items": [
        {"sku": "MC-001", "description": "Body Wash 200ml", "quantity": "500", "unit_price": "120.00", "line_total": "60,000.00"},
        {"sku": "MC-014", "description": "Coffee Face Scrub 100g", "quantity": "300", "unit_price": "95", "line_total": "28,500"},
        {"sku": "HY-203", "description": "Sunscreen SPF50 50ml", "quantity": "200", "unit_price": "Rs. 180", "line_total": "INR 36,000"},
    ],
}


def make_submitted(client_for, owner="creator1", number="PO-T-100"):
    c = client_for(owner)
    po_id = upload(c, "sample_1_digital.pdf").get_json()["po"]["id"]
    assert c.put(f"/api/pos/{po_id}", json={**GOOD_EDIT, "po_number": number}).status_code == 200
    res = c.post(f"/api/pos/{po_id}/submit")
    assert res.status_code == 200, res.get_json()
    return po_id


# ---------------------------------------------------------------- rule 1: 401
@pytest.mark.parametrize("method,path", [
    ("get", "/api/me"), ("get", "/api/pos"), ("get", "/api/pos/1"), ("put", "/api/pos/1"),
    ("post", "/api/pos/upload"), ("post", "/api/pos/1/submit"), ("post", "/api/pos/1/approve"),
    ("post", "/api/pos/1/reject"), ("get", "/api/pos/1/pdf"), ("delete", "/api/pos/1"),
])
def test_every_endpoint_needs_login(client_for, method, path):
    res = getattr(client_for(), method)(path, json={})
    assert res.status_code == 401


def test_wrong_password_and_login_by_email(client_for):
    c = client_for()
    assert c.post("/api/login", json={"login": "creator1", "password": "nope"}).status_code == 401
    assert c.post("/api/login", json={"login": "ghost", "password": "nope"}).status_code == 401
    from tests.conftest import PASSWORD
    assert c.post("/api/login", json={"login": "CREATOR1@example.com", "password": PASSWORD}).status_code == 200


def test_forged_session_cookie_is_refused(client_for):
    c = client_for()
    c.set_cookie("session", "eyJ1c2VyX2lkIjoxfQ.forged.signature")
    assert c.get("/api/pos").status_code == 401


# ---------------------------------------------------------------- upload + extraction
def test_upload_creates_draft_with_extracted_fields(client_for, storage):
    res = upload(client_for("creator1"), "sample_1_digital.pdf")
    assert res.status_code == 201
    po = res.get_json()["po"]
    assert po["status"] == "DRAFT" and po["po_number"] == "PO-2026-001"
    assert po["extraction_method"] == "text_layer" and len(po["line_items"]) == 3
    assert po["checks"]["ok"] is True
    assert len(storage.objects) == 1  # original PDF went to object storage


def test_approver_only_user_cannot_upload(client_for):
    assert upload(client_for("approver1"), "sample_1_digital.pdf").status_code == 403


def test_non_pdf_refused(client_for):
    import io
    res = client_for("creator1").post("/api/pos/upload", data={"file": (io.BytesIO(b"hello"), "x.pdf")},
                                      content_type="multipart/form-data")
    assert res.status_code == 400


def test_garbled_pdf_gives_empty_form_for_manual_entry(client_for):
    res = upload(client_for("creator1"), "sample_4_garbled.pdf").get_json()
    assert res["extraction"]["readable"] is False
    po = res["po"]
    assert po["extraction_method"] == "manual"
    assert po["po_number"] is None and po["total"] is None and po["line_items"] == []


def test_duplicate_po_number_on_upload_and_on_save(client_for):
    c1, c2 = client_for("creator1"), client_for("creator2")
    upload(c1, "sample_1_digital.pdf")
    res = upload(c2, "sample_3_resent.pdf").get_json()
    assert res["duplicate"]["po_number"] == "PO-2026-001"
    assert res["po"]["po_number"] is None  # draft saved without the clashing number

    save = c2.put(f"/api/pos/{res['po']['id']}", json={**GOOD_EDIT, "po_number": "po-2026-001"})
    assert save.status_code == 409
    text = save.get_data(as_text=True)
    assert "already exists" in text and "creator1" not in text and "ABC" not in text


def test_mismatch_total_blocks_submit(client_for):
    c = client_for("creator1")
    po_id = upload(c, "sample_2_mismatch.pdf").get_json()["po"]["id"]
    res = c.post(f"/api/pos/{po_id}/submit")
    assert res.status_code == 422
    assert "total" in res.get_json()["checks"]["errors"]


def test_checks_rerun_on_submit_whatever_the_browser_sent(client_for):
    c = client_for("creator1")
    po_id = upload(c, "sample_4_garbled.pdf").get_json()["po"]["id"]  # empty form
    res = c.post(f"/api/pos/{po_id}/submit")                            # submit without filling anything
    assert res.status_code == 422
    assert set(res.get_json()["checks"]["errors"]) >= {"po_number", "po_date", "vendor_name", "total"}


def test_unparseable_values_are_refused_not_saved(client_for):
    c = client_for("creator1")
    po_id = upload(c, "sample_1_digital.pdf").get_json()["po"]["id"]
    bad = {**GOOD_EDIT, "total": "twelve lakh", "po_date": "31-02-2026"}
    res = c.put(f"/api/pos/{po_id}", json=bad)
    assert res.status_code == 422 and set(res.get_json()["fields"]) == {"total", "po_date"}


# ---------------------------------------------------------------- rule 4: own POs only (404)
def test_creator_cannot_see_or_touch_another_creators_po(client_for):
    c1, c2 = client_for("creator1"), client_for("creator2")
    po_id = upload(c1, "sample_1_digital.pdf").get_json()["po"]["id"]
    assert c2.get(f"/api/pos/{po_id}").status_code == 404
    assert c2.put(f"/api/pos/{po_id}", json=GOOD_EDIT).status_code == 404
    assert c2.post(f"/api/pos/{po_id}/submit").status_code == 404
    assert c2.get(f"/api/pos/{po_id}/pdf").status_code == 404
    assert c2.delete(f"/api/pos/{po_id}").status_code == 404
    assert c2.get("/api/pos?view=mine").get_json()["items"] == []
    assert c2.get("/api/pos/999999").status_code == 404  # same answer as "doesn't exist"


def test_approver_cannot_open_someone_elses_draft(client_for):
    po_id = upload(client_for("creator1"), "sample_1_digital.pdf").get_json()["po"]["id"]
    assert client_for("approver1").get(f"/api/pos/{po_id}").status_code == 404


def test_submitted_po_is_locked_for_editing(client_for):
    po_id = make_submitted(client_for)
    c = client_for("creator1")
    assert c.put(f"/api/pos/{po_id}", json=GOOD_EDIT).status_code == 409
    assert c.post(f"/api/pos/{po_id}/submit").status_code == 409


# ---------------------------------------------------------------- rules 2, 3, 7
def test_non_approver_cannot_approve_or_reject(client_for):
    po_id = make_submitted(client_for)
    for user in ("creator1", "creator2"):
        c = client_for(user)
        assert c.post(f"/api/pos/{po_id}/approve").status_code == 403
        assert c.post(f"/api/pos/{po_id}/reject", json={"reason": "x"}).status_code == 403
    assert client_for("creator2").get("/api/pos?view=queue").status_code == 403


def test_nobody_approves_their_own_po_not_even_lead1(client_for):
    po_id = make_submitted(client_for, owner="lead1", number="PO-LEAD-1")
    lead = client_for("lead1")
    assert lead.post(f"/api/pos/{po_id}/approve").status_code == 403
    assert lead.post(f"/api/pos/{po_id}/reject", json={"reason": "mine"}).status_code == 403
    assert lead.get(f"/api/pos/{po_id}").get_json()["po"]["status"] == "SUBMITTED"
    # ...but another approver can.
    assert client_for("approver1").post(f"/api/pos/{po_id}/approve").status_code == 200


def test_lead1_can_approve_other_peoples_po(client_for):
    po_id = make_submitted(client_for)
    assert client_for("lead1").post(f"/api/pos/{po_id}/approve").status_code == 200


def test_approver_sees_queue_across_creators_but_cannot_edit(client_for):
    a = make_submitted(client_for, "creator1", "PO-A")
    b = make_submitted(client_for, "creator2", "PO-B")
    ap = client_for("approver1")
    ids = {p["id"] for p in ap.get("/api/pos?view=queue").get_json()["items"]}
    assert {a, b} <= ids
    assert ap.put(f"/api/pos/{a}", json=GOOD_EDIT).status_code == 403
    assert ap.get(f"/api/pos/{a}").get_json()["po"]["permissions"]["can_edit"] is False


# ---------------------------------------------------------------- rules 5, 6 + full lifecycle
def test_second_approve_is_refused(client_for):
    po_id = make_submitted(client_for)
    ap = client_for("approver1")
    assert ap.post(f"/api/pos/{po_id}/approve").status_code == 200
    assert ap.post(f"/api/pos/{po_id}/approve").status_code == 409
    assert client_for("lead1").post(f"/api/pos/{po_id}/reject", json={"reason": "late"}).status_code == 409


def test_draft_cannot_be_approved(client_for):
    c = client_for("creator1")
    po_id = upload(c, "sample_1_digital.pdf").get_json()["po"]["id"]
    c.post(f"/api/pos/{po_id}/submit")
    c2 = client_for("creator1")
    draft = upload(c2, "extra_template2_clean.pdf").get_json()["po"]["id"]
    # approver can't even see a draft -> 404, never an approval
    assert client_for("approver1").post(f"/api/pos/{draft}/approve").status_code == 404


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_reject_needs_a_reason(client_for, reason):
    po_id = make_submitted(client_for)
    res = client_for("approver1").post(f"/api/pos/{po_id}/reject", json={"reason": reason})
    assert res.status_code == 400


def test_full_lifecycle_with_history(client_for):
    po_id = make_submitted(client_for)
    ap, c = client_for("approver1"), client_for("creator1")
    assert ap.post(f"/api/pos/{po_id}/reject", json={"reason": "Wrong unit price on MC-014"}).status_code == 200
    po = c.get(f"/api/pos/{po_id}").get_json()["po"]
    assert po["status"] == "REJECTED" and po["permissions"]["can_edit"]
    # creator fixes the SAME PO and resubmits
    assert c.put(f"/api/pos/{po_id}", json={**GOOD_EDIT, "vendor_name": "ABC Industries Pvt Ltd"}).status_code == 200
    assert c.post(f"/api/pos/{po_id}/submit").status_code == 200
    assert ap.post(f"/api/pos/{po_id}/approve", json={"remark": "ok"}).status_code == 200

    po = c.get(f"/api/pos/{po_id}").get_json()["po"]
    assert po["status"] == "APPROVED"
    actions = [(h["action"], h["by"]) for h in po["history"]]
    assert actions == [("SUBMIT", "creator1"), ("REJECT", "approver1"), ("RESUBMIT", "creator1"), ("APPROVE", "approver1")]
    assert po["history"][1]["remark"] == "Wrong unit price on MC-014"
    assert all(h["at"] for h in po["history"])
    # APPROVED is final
    assert c.put(f"/api/pos/{po_id}", json=GOOD_EDIT).status_code == 409
    assert c.post(f"/api/pos/{po_id}/submit").status_code == 409
    assert c.delete(f"/api/pos/{po_id}").status_code == 409


def test_history_has_no_edit_or_delete_endpoint(client_for, db_path):
    po_id = make_submitted(client_for)
    ap = client_for("approver1")
    for method in ("put", "patch", "delete"):
        assert getattr(ap, method)(f"/api/pos/{po_id}/history").status_code in (404, 405)
    import sqlite3
    conn = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM po_actions")  # the database itself refuses


def test_pdf_opens_via_signed_link(client_for):
    po_id = make_submitted(client_for)
    res = client_for("approver1").get(f"/api/pos/{po_id}/pdf")
    assert res.status_code == 302 and "signed" in res.headers["Location"]


def test_discard_draft(client_for, storage):
    c = client_for("creator1")
    po_id = upload(c, "sample_3_resent.pdf").get_json()["po"]["id"]
    assert c.delete(f"/api/pos/{po_id}").status_code == 200
    assert c.get(f"/api/pos/{po_id}").status_code == 404
    assert storage.objects == {}


# ---------------------------------------------------------------- Core B: health + errors
def test_health_ok(app):
    res = app.test_client().get("/health")
    assert res.status_code == 200 and res.get_json()["checks"]["database"] == "ok"


def test_health_reports_database_down(broken_app):
    res = broken_app.test_client().get("/health")
    assert res.status_code == 503 and res.get_json()["status"] == "error"


def test_unexpected_errors_are_friendly(broken_app):
    res = broken_app.test_client().post("/api/login", json={"login": "creator1", "password": "x"})
    body = res.get_json()
    assert res.status_code == 500
    assert "Traceback" not in res.get_data(as_text=True) and body["request_id"]
