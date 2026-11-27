from datetime import date

import pytest

from app.extraction import assess_text, extract_po, ocr_available
from app.validation import run_checks
from tests.conftest import sample_path


def _read(name, ocr=False):
    with open(sample_path(name), "rb") as fh:
        return extract_po(fh.read(), ocr_enabled=ocr)


def test_sample1_header_and_line_items():
    r = _read("sample_1_digital.pdf")
    assert r["readable"] and r["method"] == "text_layer"
    f = r["fields"]
    assert f["po_number"] == "PO-2026-001"
    assert f["po_date"] == date(2026, 11, 15)
    assert f["vendor_name"] == "ABC Industries"
    assert f["total_paise"] == 12450000
    assert [l["sku"] for l in r["lines"]] == ["MC-001", "MC-014", "HY-203"]
    assert r["lines"][1]["description"] == "Coffee Face Scrub 100g"
    assert run_checks(f, r["lines"])["ok"]


def test_sample2_total_mismatch_caught():
    r = _read("sample_2_mismatch.pdf")
    checks = run_checks(r["fields"], r["lines"])
    assert not checks["ok"] and checks["totals_match"] is False


def test_sample4_garbled_layer_is_not_used():
    r = _read("sample_4_garbled.pdf", ocr=False)
    assert not r["readable"] and r["method"] == "manual"
    assert all(v is None for v in r["fields"].values()) and r["lines"] == []
    assert "garbled" in r["message"] or "no readable text" in r["message"]


@pytest.mark.skipif(not ocr_available(), reason="tesseract not installed")
def test_sample4_read_by_ocr_goes_through_checks():
    r = _read("sample_4_garbled.pdf", ocr=True)
    assert r["method"] == "ocr"
    assert r["fields"]["po_number"]
    run_checks(r["fields"], r["lines"])  # must not raise; mistakes surface as check failures


def test_wrapped_description_and_other_labels():
    r = _read("extra_wrapped_rs.pdf")
    assert r["fields"]["po_number"] == "PO-2026-077"            # "P.O. #" label
    assert r["fields"]["po_date"] == date(2026, 11, 15)          # "15 Nov 2026"
    assert r["lines"][1]["description"].endswith("(Pack of 2, Hazelnut)")
    assert run_checks(r["fields"], r["lines"])["ok"]


def test_second_template_with_serial_column():
    r = _read("extra_template2_clean.pdf")
    assert r["fields"]["po_number"] == "PO-2026-004"
    assert r["fields"]["vendor_name"] == "Sunrise Packaging Co."
    assert len(r["lines"]) == 3 and run_checks(r["fields"], r["lines"])["ok"]


def test_scan_without_text_layer():
    r = _read("extra_scanned_no_text.pdf", ocr=False)
    assert not r["readable"] and "scan" in r["message"]


def test_assess_text_rejects_gibberish_even_when_long():
    gibberish = "Wbyjohzl Vykly Uv. Zbwwsply Klspclyf Htvbua " * 20
    assert assess_text(gibberish)[0] is False


def test_not_a_pdf_does_not_crash():
    r = extract_po(b"%PDF-1.4 this is not really a pdf")
    assert r["readable"] is False and r["method"] == "manual"
