"""PDF -> PO fields. Three stages:

  1. get_text_layer()  read the PDF's own text layer with pdfplumber
  2. assess_text()     decide whether that text is USABLE (not just whether it exists):
                         - almost no characters          -> a scan / image-only PDF
                         - many (cid:NN) or odd symbols  -> broken font encoding (garbled)
                         - too few PO words (order, total, qty, ...) -> gibberish layer
  3. parse_po_text()   pull header fields and line items out of usable text

If the text layer is unusable and OCR is enabled, the page is rendered to an
image (pdftoppm) and read by Tesseract; the OCR text then goes through the SAME
assess -> parse steps and, later, the same server-side checks. If nothing usable
comes out, the form is left EMPTY for manual entry — we never fill in garbage.
"""
import glob
import io
import re
import shutil
import subprocess
import tempfile
from .validation import normalize_po_number, parse_date, parse_money, parse_quantity

MAX_PAGES = 5

# ------------------------------------------------------------------ 1. text layer
def get_text_layer(pdf_bytes):
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = pdf.pages[:MAX_PAGES]
        return "\n".join((page.extract_text() or "") for page in pages)


# ------------------------------------------------------------------ 2. is the text usable?
PO_WORDS = {
    "purchase", "order", "po", "p.o.", "total", "grand", "amount", "vendor", "supplier", "date",
    "qty", "quantity", "rate", "price", "unit", "description", "sku", "item", "code", "sr.", "no.",
}
_ALLOWED = re.compile(r"[A-Za-z0-9\s.,:;'\"()\-/&#%@+*₹=_\[\]|!?]")


def assess_text(text):
    """Return (usable: bool, reason: str). `reason` is shown to the user when not usable."""
    compact = re.sub(r"\s+", "", text or "")
    if len(compact) < 40:
        return False, (
            "This PDF has no readable text layer — it looks like a scanned image, "
            "so it can't be read automatically. Please type the details from the PDF."
        )
    cid_hits = len(re.findall(r"\(cid:\d+\)", text))
    odd_chars = sum(1 for ch in re.sub(r"\(cid:\d+\)", "", text) if not _ALLOWED.match(ch))
    odd_ratio = (odd_chars + cid_hits) / max(len(compact), 1)
    words = {w.strip(":,").lower() for w in text.split()}
    po_word_hits = len(words & PO_WORDS)

    if odd_ratio > 0.03 or po_word_hits < 3:
        return False, (
            "This PDF has a text layer, but the text is garbled (the characters don't form "
            "real words), so it can't be read automatically. Please type the details from the PDF."
        )
    return True, "ok"


# ------------------------------------------------------------------ 3. parsing
_MONEY = r"(?:₹|rs\.?|inr)?\s*\d[\d,]*(?:\.\d{1,2})?(?:/-)?"
_PO_NUMBER = re.compile(
    r"(?:purchase\s*order\s*(?:no\.?|number|#)|p\.?\s*o\.?\s*(?:no\.?|number|num\.?|#)|order\s*(?:no\.?|number|#))"
    r"\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",
    re.I,
)
_DATE = re.compile(
    r"(?:p\.?\s*o\.?\s*date|order\s*date|date)\s*[:\-]?\s*"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{2,4}|\d{1,2}(?:st|nd|rd|th)?[\s\-]+[A-Za-z]{3,9}[\s,\-]+\d{2,4})",
    re.I,
)
_VENDOR = re.compile(r"\b(?:vendor|supplier)(?:\s*name)?\s*[:\-]?\s*(.+)$", re.I)
_VENDOR_STOP = re.compile(
    r"\s+(?:p\.?\s*o\.?\s*date|order\s*date|date|delivery|deliver\s*to|gstin|gst|phone|ph\.?|email|address)\b.*$",
    re.I,
)
_TOTALS = [  # (priority, pattern) — higher priority wins
    (3, re.compile(r"(?:grand\s*total|p\.?\s*o\.?\s*total|total\s*amount|net\s*total|total\s*payable)"
                   r"\s*[:\-]?\s*(" + _MONEY + r")\s*$", re.I)),
    (1, re.compile(r"(?<!sub\s)(?<!sub)\btotal\s*[:\-]?\s*(" + _MONEY + r")\s*$", re.I)),
]
_ROW = re.compile(
    r"^(?:\d{1,3}[.)]?\s+)?"                       # optional "Sr." serial number
    r"([A-Z]{1,6}[-/]?\d{1,6}[A-Z0-9\-]*)\s+"       # SKU like MC-001, PK-110, HY203
    r"(.+?)\s+"                                     # description (shortest that fits)
    r"(\d[\d,]*(?:\.\d+)?)\s+"                      # quantity
    r"(" + _MONEY + r")\s+"                         # unit price
    r"(" + _MONEY + r")\s*$",                       # line total
    re.I,
)
_SKU_START = re.compile(r"^(?:\d{1,3}[.)]?\s+)?[A-Z]{1,6}[-/]?\d{1,6}[A-Z0-9\-]*\s+\S", re.I)
_NOT_A_WRAP =re.compile(r"total|signator|terms|vendor|supplier|order|date|^sr\.?\b|^sku\b|amount", re.I)


def _first(pattern, text):
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def parse_po_text(text):
    """Extract fields from usable text. Only values that parse cleanly are returned;
    anything doubtful is left empty (with a warning) for the user to fill."""
    fields = {"po_number": None, "po_date": None, "vendor_name": None, "total_paise": None}
    warnings = []
    lines_text = [re.sub(r"[ \t]+", " ", l).strip() for l in text.splitlines()]
    lines_text = [l for l in lines_text if l]

    raw_number = _first(_PO_NUMBER, text)
    if raw_number and re.search(r"\d", raw_number):
        fields["po_number"] = normalize_po_number(raw_number)

    raw_date = _first(_DATE, text)
    if raw_date:
        try:
            fields["po_date"] = parse_date(re.sub(r"\s*([./-])\s*", r"\1", raw_date))
        except ValueError:
            warnings.append(f"Could not understand the date '{raw_date}'.")

    for line in lines_text:
        m = _VENDOR.search(line)
        if m:
            name = _VENDOR_STOP.sub("", m.group(1)).strip(" :-—–")
            if name:
                fields["vendor_name"] = name
                break

    best = None
    for line in lines_text:
        for priority, pattern in _TOTALS:
            m = pattern.search(line)
            if m and (best is None or priority >= best[0]):
                best = (priority, m.group(1))
                break
    if best:
        try:
            fields["total_paise"] = parse_money(best[1])
        except ValueError:
            warnings.append(f"Could not understand the total '{best[1]}'.")

    items = []
    in_table = False
    for line in lines_text:
        m = _ROW.match(line)
        if m:
            in_table = True
            sku, desc, qty, price, amount = m.groups()
            try:
                items.append({
                    "sku": sku.upper(),
                    "description": desc.strip(),
                    "quantity": parse_quantity(qty),
                    "unit_price_paise": parse_money(price),
                    "line_total_paise": parse_money(amount),
                })
            except ValueError:
                warnings.append(f"Skipped a line item that could not be read: '{line}'.")
            continue
        if _SKU_START.match(line) and re.search(r"\d", line[8:]):
            # Looks like an item row but didn't parse (e.g. OCR read ₹ as '='). Never guess.
            warnings.append(f"This line looks like an item but could not be read, please add it by hand: '{line}'")
            in_table = True
            continue
        if in_table and re.search(r"\btotal\b", line, re.I):
            in_table = False  # reached the totals block
            continue
        # A wrapped description: text-only line straight after a row.
        if in_table and items and not re.search(r"\d[\d,]*\.\d{2}", line) and not _NOT_A_WRAP.search(line):
            items[-1]["description"] = f"{items[-1]['description']} {line}"

    return fields, items, warnings


# ------------------------------------------------------------------ OCR (optional)
def ocr_available():
    return shutil.which("tesseract") is not None and shutil.which("pdftoppm") is not None


def ocr_text(pdf_bytes, pages=2):
    """Render the first pages at 300 dpi and read them with Tesseract."""
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        src = f"{tmp}/in.pdf"
        with open(src, "wb") as fh:
            fh.write(pdf_bytes)
        subprocess.run(
            ["pdftoppm", "-r", "300", "-gray", "-png", "-f", "1", "-l", str(pages), src, f"{tmp}/p"],
            check=True, timeout=60, capture_output=True,
        )
        for image in sorted(glob.glob(f"{tmp}/p*.png")):
            # --psm 4 = "one column of text of variable sizes": keeps table rows
            # together and copes with boxed header grids (psm 6 lost labels there).
            result = subprocess.run(
                ["tesseract", image, "-", "--psm", "4", "-l", "eng"],
                check=True, timeout=60, capture_output=True, text=True,
            )
            out.append(result.stdout)
    return clean_ocr_text("\n".join(out))


def clean_ocr_text(text):
    """Fix OCR misreads we have seen: the ₹ sign comes out as %, ¥, € or £ in front
    of an amount, and dashes come out as long dashes. Nothing else is "corrected" —
    wrong digits are left for the checks to catch."""
    text = re.sub(r"[%¥€£](?=\s?\d)", "₹", text)
    return text.replace("—", "-").replace("–", "-")


# ------------------------------------------------------------------ entry point
def _empty(method, message, warnings=None):
    return {
        "readable": False,
        "method": method,
        "message": message,
        "warnings": warnings or [],
        "fields": {"po_number": None, "po_date": None, "vendor_name": None, "total_paise": None},
        "lines": [],
    }


def extract_po(pdf_bytes, ocr_enabled=False):
    try:
        text = get_text_layer(pdf_bytes)
    except Exception:
        return _empty("manual", "This PDF could not be opened (it may be damaged or password-protected). "
                                "Please type the details from the document.")

    usable, reason = assess_text(text)
    if usable:
        fields, lines, warnings = parse_po_text(text)
        if fields["po_number"] or fields["total_paise"] is not None:
            return {
                "readable": True,
                "method": "text_layer",
                "message": "Read from the PDF's text layer. Please review every value before submitting.",
                "warnings": warnings,
                "fields": fields,
                "lines": lines,
            }
        reason = ("This PDF has text, but no purchase-order fields could be found in it. "
                  "Please type the details from the PDF.")

    if ocr_enabled and ocr_available():
        try:
            text = ocr_text(pdf_bytes)
        except Exception:
            text = ""
        ocr_usable, _ = assess_text(text)
        if ocr_usable:
            fields, lines, warnings = parse_po_text(text)
            if fields["po_number"] and fields["total_paise"] is not None:
                return {
                    "readable": True,
                    "method": "ocr",
                    "message": ("The PDF's own text layer was unusable, so it was read with OCR (image-to-text). "
                                "OCR can misread digits: check every value against the PDF before submitting."),
                    "warnings": warnings,
                    "fields": fields,
                    "lines": lines,
                }
    return _empty("manual", reason)

