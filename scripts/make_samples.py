"""Generate test PDFs that imitate the four samples described in the brief, plus
two extra "messy" ones. Dev-only (needs reportlab + pdftoppm).

    python scripts/make_samples.py            # writes into samples/generated/

The real sample_1..4 PDFs from the brief should be placed in samples/ as well;
the tests run against whichever are present.
"""
import os
import subprocess
import sys
import tempfile

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

OUT = os.path.join(os.path.dirname(__file__), "..", "samples", "generated")

# A font with the ₹ glyph, if available; otherwise fall back to "Rs."
RUPEE = "Rs."
FONT, BOLD = "Helvetica", "Helvetica-Bold"
for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",):
    if os.path.exists(path):
        pdfmetrics.registerFont(TTFont("DejaVu", path))
        bold = path.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold if os.path.exists(bold) else path))
        FONT, BOLD, RUPEE = "DejaVu", "DejaVu-Bold", "₹"

ITEMS = [
    ("MC-001", "Body Wash 200ml", 500, "120.00", "60,000.00"),
    ("MC-014", "Coffee Face Scrub 100g", 300, "95.00", "28,500.00"),
    ("HY-203", "Sunscreen SPF50 50ml", 200, "180.00", "36,000.00"),
]


def template_one(path, po_number="PO-2026-001", total="1,24,500.00", items=ITEMS, signed=False,
                 date_text="15-11-2026", number_label="PO Number", money=None, wrap=None):
    money = money or RUPEE
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    y = h - 60
    c.setFont(BOLD, 16)
    c.drawCentredString(w / 2, y, "PEP BRANDS")
    c.setFont(BOLD, 12)
    c.drawCentredString(w / 2, y - 18, "PURCHASE ORDER")
    y -= 40
    c.line(40, y, w - 40, y)
    y -= 18
    c.setFont(FONT, 10)
    c.drawString(45, y, f"{number_label} : {po_number}")
    c.drawString(340, y, f"PO Date : {date_text}")
    y -= 16
    c.drawString(45, y, "Vendor    : ABC Industries")
    y -= 14
    c.drawString(45 + 56, y, "Plot 14, Industrial Area, Pune")
    y -= 12
    c.line(40, y, w - 40, y)
    y -= 16
    c.setFont(BOLD, 10)
    for x, label in ((45, "SKU"), (110, "Description"), (300, "Qty")):
        c.drawString(x, y, label)
    c.drawRightString(440, y, "Unit Price")
    c.drawRightString(545, y, "Amount")
    c.setFont(FONT, 10)
    for sku, desc, qty, price, amount in items:
        y -= 16
        first = desc
        second = None
        if wrap and sku in wrap:
            first, second = wrap[sku]
        c.drawString(45, y, sku)
        c.drawString(110, y, first)
        c.drawRightString(330, y, str(qty))
        c.drawRightString(440, y, f"{money}{price}")
        c.drawRightString(545, y, f"{money}{amount}")
        if second:
            y -= 13
            c.drawString(110, y, second)
    y -= 12
    c.line(40, y, w - 40, y)
    y -= 18
    c.setFont(BOLD, 11)
    c.drawRightString(440, y, "PO TOTAL :")
    c.drawRightString(545, y, f"{money}{total}")
    y -= 40
    c.setFont(FONT, 10)
    c.drawString(45, y, "Authorised Signatory: " + ("(signed) R. Mehta" if signed else "______________"))
    c.save()


def template_two(path):
    """Different layout: boxed header grid, 'Purchase Order No.', 'Order Date', Sr. column, Rs., Grand Total."""
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(w / 2, h - 60, "PEP BRANDS PRIVATE LIMITED")
    c.setFont("Helvetica", 10)
    c.drawCentredString(w / 2, h - 76, "PURCHASE ORDER")
    top = h - 100
    grid = [
        ("Purchase Order No.", "PO-2026-004", "Order Date", "20/11/2026"),
        ("Supplier", "Sunrise Packaging Co.", "Delivery", "Bhiwandi WH"),
    ]
    for r, (l1, v1, l2, v2) in enumerate(grid):
        y = top - r * 24
        for x, wd in ((40, 110), (150, 150), (300, 90), (390, 165)):
            c.rect(x, y - 24, wd, 24)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(45, y - 16, l1)
        c.drawString(305, y - 16, l2)
        c.setFont("Helvetica", 9)
        c.drawString(155, y - 16, v1)
        c.drawString(395, y - 16, v2)
    rows = [
        ("1", "PK-110", "Amber Bottle 200ml", "1000", "Rs. 12.50", "Rs. 12,500.00"),
        ("2", "PK-215", "Flip Cap 24mm", "1000", "Rs. 3.20", "Rs. 3,200.00"),
        ("3", "LB-031", "Front Label Coffee Wash", "1000", "Rs. 1.80", "Rs. 1,800.00"),
    ]
    y = top - 80
    cols = [40, 70, 140, 330, 380, 460, 555]
    heads = ["Sr.", "Item Code", "Description", "Qty", "Rate", "Amount"]
    c.setFont("Helvetica-Bold", 9)
    for i, head in enumerate(heads):
        c.rect(cols[i], y - 18, cols[i + 1] - cols[i], 18)
        c.drawString(cols[i] + 4, y - 12, head)
    c.setFont("Helvetica", 9)
    for row in rows:
        y -= 18
        for i, val in enumerate(row):
            c.rect(cols[i], y - 18, cols[i + 1] - cols[i], 18)
            c.drawString(cols[i] + 4, y - 12, val)
    y -= 36
    c.setFont("Helvetica-Bold", 10)
    c.drawString(380, y, "Grand Total")
    c.drawString(462, y, "Rs. 17,500.00")
    c.save()


def garble(text):
    """Simulate a broken font encoding: every letter/digit maps to a different glyph."""
    out = []
    for ch in text:
        if ch.isalpha():
            base = "a" if ch.islower() else "A"
            out.append(chr((ord(ch) - ord(base) + 7) % 26 + ord(base)))
        elif ch.isdigit():
            out.append("¤§¶†‡•°±µ¿"[int(ch)])
        else:
            out.append(ch)
    return "".join(out)


def make_garbled(src_pdf, out_pdf):
    """Looks normal (page is an image of the real PO) but the hidden text layer is garbage."""
    import pdfplumber

    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", "200", "-png", "-singlefile", src_pdf, f"{tmp}/page"], check=True)
        with pdfplumber.open(src_pdf) as pdf:
            words = pdf.pages[0].extract_words()
            page_h = float(pdf.pages[0].height)
        c = canvas.Canvas(out_pdf, pagesize=A4)
        w, h = A4
        c.drawImage(ImageReader(f"{tmp}/page.png"), 0, 0, width=w, height=h)
        text = c.beginText()
        text.setTextRenderMode(3)  # invisible, like an OCR'd or badly-encoded layer
        text.setFont("Helvetica", 9)
        for word in words:
            text.setTextOrigin(word["x0"], page_h - word["bottom"])
            text.textOut(garble(word["text"]))
        c.drawText(text)
        c.save()


def main():
    os.makedirs(OUT, exist_ok=True)
    j = lambda name: os.path.join(OUT, name)  # noqa: E731
    template_one(j("sample_1_digital.pdf"))
    template_one(j("sample_2_mismatch.pdf"), total="1,42,500.00")
    template_one(j("sample_3_resent.pdf"), signed=True)
    with tempfile.TemporaryDirectory() as tmp:
        clean = os.path.join(tmp, "t2.pdf")
        template_two(clean)
        make_garbled(clean, j("sample_4_garbled.pdf"))
        template_two(j("extra_template2_clean.pdf"))
    # Messy variant: other label, written-out date, "Rs." money, wrapped description
    template_one(
        j("extra_wrapped_rs.pdf"), po_number="PO-2026-077", number_label="P.O. #", date_text="15 Nov 2026",
        money="Rs. ", wrap={"MC-014": ("Coffee Face Scrub 100g", "(Pack of 2, Hazelnut)")},
    )
    # A scan: only an image, no text layer at all
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "s.pdf")
        template_one(src, po_number="PO-2026-090")
        subprocess.run(["pdftoppm", "-r", "150", "-png", "-singlefile", src, f"{tmp}/p"], check=True)
        c = canvas.Canvas(j("extra_scanned_no_text.pdf"), pagesize=A4)
        c.drawImage(ImageReader(f"{tmp}/p.png"), 0, 0, width=A4[0], height=A4[1])
        c.save()
    print("wrote samples to", os.path.abspath(OUT))


if __name__ == "__main__":
    sys.exit(main())
