# Demo purchase orders

Thirteen digital PO PDFs for trying the app, each covering one case from the brief's "checks" and "messiness" lists.
Every file was uploaded to the live app on 28-11-2026, and the result below is what the server returned.
Upload them as `creator1` or `creator2` (password `PepDemo@2026`).

| File | PO number | What it shows | Result on upload |
|---|---|---|---|
| `demo_01_packaging_clean.pdf` | PO-2026-101 | Clean PO, 3 lines | All checks pass → can submit |
| `demo_02_raw_material_clean.pdf` | PO-2026-102 | Clean PO, 2 lines (good for the reject → resubmit demo) | All checks pass |
| `demo_03_cartons_mismatch.pdf` | PO-2026-103 | Printed total ₹28,600 but lines add up to ₹26,600 | **PO maths fails**, submit blocked |
| `demo_04_order_no_label.pdf` | PO-2026-104 | Label `Order No.`, date `15/11/2026` | Read correctly, all checks pass |
| `demo_05_po_hash_inr.pdf` | PO-2026-105 | Label `P.O. #`, money as `INR 3,200.00`, date `18.11.2026` | Read correctly, all checks pass |
| `demo_06_written_date.pdf` | PO-2026-106 | Date `26 Nov 2026`, 4 lines | Stored as `2026-11-26`, all checks pass |
| `demo_07_wrapped_description.pdf` | PO-2026-107 | Descriptions wrap onto a second line | Still 2 line items, all checks pass |
| `demo_08_line_maths_error.pdf` | PO-2026-108 | 50 × ₹380 typed as ₹1,90,000 (the brief's "extra zero" typo) | **Line maths fails** on line 2 |
| `demo_09_many_lines_lakhs.pdf` | PO-2026-109 | 6 lines, total ₹3,10,400 (lakh grouping), signed | All checks pass |
| `demo_10_plain_amounts.pdf` | PO-2026-110 | Amounts with no currency sign (`14,400.00`) | Read correctly, all checks pass |
| `demo_11_zero_quantity.pdf` | PO-2026-111 | One line has quantity 0 | **"Quantity must be positive"** |
| `demo_12_missing_vendor.pdf` | PO-2026-112 | No vendor on the PO | **"Vendor name is required"** |
| `demo_13_duplicate_of_101.pdf` | PO-2026-101 | Re-sent, signed copy of demo 01 | **"PO-2026-101 already exists"**, owner not shown |

A PO number can be used only once, so after a file has been uploaded once, uploading it again shows the duplicate message.
That is the database's `UNIQUE(po_number)` constraint working. To demo a file again, type a new PO number into the form.
