from datetime import date
from decimal import Decimal

import pytest

from app.validation import normalize_po_number, paise_to_str, parse_date, parse_money, run_checks


@pytest.mark.parametrize("text", ["₹1,24,500.00", "Rs. 124500", "INR 1,24,500", "124,500", "Rs 1,24,500/-", 124500])
def test_money_formats_all_parse_to_the_same_paise(text):
    assert parse_money(text) == 12450000


@pytest.mark.parametrize("text", ["", "abc", "-500", "1.2.3", "₹", "12,34x"])
def test_bad_money_is_refused(text):
    with pytest.raises(ValueError):
        parse_money(text)


def test_money_is_exact_not_float():
    assert parse_money("0.10") + parse_money("0.20") == parse_money("0.30")  # 0.1+0.2 != 0.3 in float
    assert paise_to_str(12450000) == "1,24,500.00"
    assert paise_to_str(99) == "0.99"


@pytest.mark.parametrize("text", ["15-11-2026", "15/11/2026", "15.11.2026", "15 Nov 2026", "15-Nov-2026", "2026-11-15"])
def test_date_formats_are_day_month_year(text):
    assert parse_date(text) == date(2026, 11, 15)


def test_ambiguous_date_is_read_day_first():
    assert parse_date("03/04/2026") == date(2026, 4, 3)


def test_invalid_date_refused():
    with pytest.raises(ValueError):
        parse_date("31-02-2026")


def test_po_number_normalised():
    assert normalize_po_number(" po-2026-001 ") == "PO-2026-001"


def _po(total="1,24,500.00"):
    return {"po_number": "PO-1", "po_date": date(2026, 11, 15), "vendor_name": "ABC", "total_paise": parse_money(total)}


def _line(qty, price, total, sku="A-1"):
    return {"sku": sku, "description": "x", "quantity": Decimal(qty), "unit_price_paise": parse_money(price),
            "line_total_paise": parse_money(total)}


GOOD_LINES = [_line("500", "120", "60,000"), _line("300", "95", "28,500"), _line("200", "180", "36,000")]


def test_clean_po_passes():
    result = run_checks(_po(), GOOD_LINES)
    assert result["ok"] and result["totals_match"] is True


def test_printed_total_mismatch_is_flagged():
    result = run_checks(_po("1,42,500.00"), GOOD_LINES)
    assert not result["ok"]
    assert "1,24,500.00" in result["errors"]["total"] and "1,42,500.00" in result["errors"]["total"]


def test_line_maths_within_one_rupee():
    assert run_checks(_po("60,000.99"), [_line("500", "120", "60,000.99")])["ok"]
    bad = run_checks(_po("60,002"), [_line("500", "120", "60,002")])
    assert "line_total" in bad["line_errors"]["0"]


def test_zero_or_negative_quantity_refused():
    result = run_checks(_po("0"), [_line("0", "120", "0")])
    assert "quantity" in result["line_errors"]["0"]


def test_required_fields():
    result = run_checks({"po_number": None, "po_date": None, "vendor_name": " ", "total_paise": None}, [])
    assert set(result["errors"]) == {"po_number", "po_date", "vendor_name", "total"}


def test_no_line_items_is_not_silently_passed():
    result = run_checks(_po(), [])
    assert result["line_items_checked"] is False
    assert any("Line items not checked" in n for n in result["notes"])
