"""Parsing and the five PO checks. Pure functions: no Flask, no database.

Money is converted to integer paise with Decimal — never float — so
₹1,24,500.00 / Rs. 124500 / INR 1,24,500 / 124,500 all become 12450000 exactly.
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

TOLERANCE_PAISE = 100  # "within ₹1"

_CURRENCY = re.compile(r"^(?:₹|rs\.?|inr|r\$)\s*", re.IGNORECASE)
_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")


# ---------------------------------------------------------------- money / numbers
def parse_money(value):
    """'₹1,24,500.00' -> 12450000 (paise). Raises ValueError if it is not a valid amount."""
    if value is None:
        raise ValueError("missing")
    if isinstance(value, bool):
        raise ValueError("not a number")
    if isinstance(value, int):
        return value * 100
    text = str(value).strip()
    text = _CURRENCY.sub("", text)
    text = text.replace(",", "").replace(" ", "").replace(" ", "")
    if text.endswith("/-"):  # common Indian notation: Rs. 500/-
        text = text[:-2]
    if not _NUMBER.match(text):
        raise ValueError("not a valid amount")
    amount = Decimal(text)
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_quantity(value):
    if value is None or isinstance(value, bool):
        raise ValueError("missing")
    text = str(value).strip().replace(",", "")
    try:
        qty = Decimal(text)
    except InvalidOperation:
        raise ValueError("not a number") from None
    if not qty.is_finite():
        raise ValueError("not a number")
    return qty.quantize(Decimal("0.001"))


def paise_to_str(paise):
    """12450000 -> '1,24,500.00' (Indian digit grouping)."""
    if paise is None:
        return ""
    sign = "-" if paise < 0 else ""
    rupees, p = divmod(abs(int(paise)), 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return f"{sign}{s}.{p:02d}"


# ---------------------------------------------------------------- dates
_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_DMY = re.compile(r"^(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{2}|\d{4})$")
_D_MON_Y = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[\s\-/.,]*([A-Za-z]{3,9})[\s\-/.,]*(\d{2}|\d{4})$")
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value):
    """Accepts 15-11-2026, 15/11/2026, 15.11.2026, 15 Nov 2026, 2026-11-15.
    Always day-month-year (never US month-first). Returns a datetime.date."""
    if value is None:
        raise ValueError("missing")
    if isinstance(value, date):
        return value
    text = str(value).strip()
    m = _ISO.match(text)
    if m:
        y, mo, d = map(int, m.groups())
        return date(y, mo, d)
    m = _DMY.match(text)
    if m:
        d, mo, y = m.groups()
        return date(_year(y), int(mo), int(d))
    m = _D_MON_Y.match(text)
    if m:
        d, mon, y = m.groups()
        month = _MONTHS.get(mon.lower())
        if month is None:
            raise ValueError("unknown month")
        return date(_year(y), month, int(d))
    raise ValueError("unrecognised date")


def _year(y):
    y = int(y)
    return 2000 + y if y < 100 else y


def to_iso(d):
    if d is None:
        return None
    if isinstance(d, (date, datetime)):
        return d.strftime("%Y-%m-%d")
    return str(d)[:10]


def normalize_po_number(value):
    """'  po-2026-001 ' -> 'PO-2026-001' so the UNIQUE constraint catches case/space variants."""
    if value is None:
        return None
    text = re.sub(r"\s+", "", str(value)).upper()
    return text or None


# ---------------------------------------------------------------- the five checks
def run_checks(po, lines):
    """Run checks 1-4 on a PO (check 5, duplicates, is the database's UNIQUE constraint).

    `po` has po_number, po_date, vendor_name, total_paise; each line has sku,
    description, quantity (Decimal), unit_price_paise, line_total_paise.
    Returns a dict the UI uses to highlight fields. `ok` False blocks submit.
    """
    errors = {}          # header field -> message
    line_errors = {}     # line index -> {field: message}
    notes = []

    # 1. Required fields
    if not po.get("po_number"):
        errors["po_number"] = "PO number is required."
    if not po.get("po_date"):
        errors["po_date"] = "PO date is required."
    if not (po.get("vendor_name") or "").strip():
        errors["vendor_name"] = "Vendor name is required."
    total = po.get("total_paise")
    if total is None:
        errors["total"] = "PO total is required."
    elif total <= 0:
        errors["total"] = "PO total must be greater than zero."

    # 2 + 3. Valid positive numbers and line maths
    calculated = 0
    for i, line in enumerate(lines):
        e = {}
        qty, price, line_total = line.get("quantity"), line.get("unit_price_paise"), line.get("line_total_paise")
        if not (line.get("sku") or line.get("description")):
            e["description"] = "Each line needs a SKU or description."
        if qty is None:
            e["quantity"] = "Quantity is required."
        elif qty <= 0:
            e["quantity"] = "Quantity must be positive."
        if price is None:
            e["unit_price"] = "Unit price is required."
        elif price <= 0:
            e["unit_price"] = "Unit price must be positive."
        if line_total is None:
            e["line_total"] = "Line total is required."
        if "quantity" not in e and "unit_price" not in e and line_total is not None:
            expected = (Decimal(qty) * Decimal(price)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            if abs(expected - line_total) > TOLERANCE_PAISE:
                e["line_total"] = (
                    f"Quantity × unit price = ₹{paise_to_str(int(expected))}, "
                    f"but the line total says ₹{paise_to_str(line_total)}."
                )
        if line_total is not None:
            calculated += line_total
        if e:
            line_errors[i] = e

    # 4. PO maths
    totals_match = None
    if not lines:
        notes.append("Line items not checked: this PO has no line items.")
    elif total is not None:
        totals_match = abs(calculated - total) <= TOLERANCE_PAISE
        if not totals_match:
            errors["total"] = (
                f"Line items add up to ₹{paise_to_str(calculated)}, "
                f"but the PO total says ₹{paise_to_str(total)}."
            )

    return {
        "ok": not errors and not line_errors,
        "errors": errors,
        "line_errors": {str(k): v for k, v in line_errors.items()},
        "notes": notes,
        "line_items_checked": bool(lines),
        "calculated_total_paise": calculated if lines else None,
        "totals_match": totals_match,
    }
