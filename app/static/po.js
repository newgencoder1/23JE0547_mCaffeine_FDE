const poId = Number(window.location.pathname.split("/").pop());
const HEADER_FIELDS = ["po_number", "po_date", "vendor_name", "total"];
const LINE_FIELDS = ["sku", "description", "quantity", "unit_price", "line_total"];
let po, me;

function fmtPaise(p) {
  if (p === null || p === undefined) return "";
  const rupees = Math.floor(Math.abs(p) / 100).toLocaleString("en-IN");
  return `${p < 0 ? "-" : ""}${rupees}.${String(Math.abs(p) % 100).padStart(2, "0")}`;
}

function banner(message, kind = "error") {
  const el = document.createElement("div");
  el.className = `alert alert-${kind}`;
  el.textContent = message;
  document.getElementById("banners").appendChild(el);
}
function clearBanners() { document.getElementById("banners").innerHTML = ""; }

function lineRow(line = {}, editable = true) {
  const tr = document.createElement("tr");
  tr.innerHTML = `<td class="small muted"></td>` + LINE_FIELDS.map((f) => {
    const num = ["quantity", "unit_price", "line_total"].includes(f);
    return `<td${num ? ' class="num"' : ""}><input data-line-field="${f}" value="${esc(line[f] ?? "")}"
      ${editable ? "" : "readonly"} ${num ? 'style="text-align:right"' : ""}><div class="err-text"></div></td>`;
  }).join("") + `<td>${editable ? '<button type="button" class="link small remove">remove</button>' : ""}</td>`;
  const rm = tr.querySelector(".remove");
  if (rm) rm.onclick = () => { tr.remove(); renumber(); };
  return tr;
}

function renumber() {
  document.querySelectorAll("#lines tr").forEach((tr, i) => (tr.firstElementChild.textContent = i + 1));
}

function collect() {
  const data = {};
  HEADER_FIELDS.forEach((f) => (data[f] = document.getElementById(f).value));
  data.line_items = [...document.querySelectorAll("#lines tr")]
    .map((tr) => Object.fromEntries(LINE_FIELDS.map((f) => [f, tr.querySelector(`[data-line-field="${f}"]`).value])))
    .filter((l) => LINE_FIELDS.some((f) => l[f].trim() !== ""));
  return data;
}

function clearErrors() {
  document.querySelectorAll(".field-error").forEach((el) => el.classList.remove("field-error"));
  document.querySelectorAll(".err-text").forEach((el) => (el.textContent = ""));
}

// Highlight failed fields: header errors by name, line errors by row index.
function showErrors(fields = {}, lineErrors = {}) {
  Object.entries(fields).forEach(([f, msg]) => {
    const input = document.getElementById(f === "reason" ? "remark" : f);
    if (input) input.classList.add("field-error");
    const t = document.querySelector(`[data-err="${f}"]`);
    if (t) t.textContent = msg;
  });
  const rows = document.querySelectorAll("#lines tr");
  Object.entries(lineErrors).forEach(([idx, errs]) => {
    const tr = rows[Number(idx)];
    if (!tr) return;
    Object.entries(errs).forEach(([f, msg]) => {
      const input = tr.querySelector(`[data-line-field="${f}"]`);
      if (!input) return;
      input.classList.add("field-error");
      input.nextElementSibling.textContent = msg;
    });
  });
}

function renderChecks(checks, editable) {
  const ul = document.getElementById("checks");
  const items = [];
  const req = ["po_number", "po_date", "vendor_name"].filter((f) => checks.errors[f]);
  const totalMissing = checks.errors.total && /required|greater/.test(checks.errors.total);
  items.push(req.length || totalMissing
    ? `<li class="fail">✗ Required fields: ${req.length + (totalMissing ? 1 : 0)} missing or invalid (highlighted above)</li>`
    : `<li class="pass">✓ Required fields present (PO number, date, vendor, total)</li>`);
  const lineIssues = Object.keys(checks.line_errors).length;
  if (checks.line_items_checked) {
    items.push(lineIssues
      ? `<li class="fail">✗ ${lineIssues} line item(s) have problems: positive numbers and quantity × unit price = line total (within ₹1)</li>`
      : `<li class="pass">✓ Every line: positive numbers and quantity × unit price = line total (within ₹1)</li>`);
    items.push(checks.totals_match === false
      ? `<li class="fail">✗ ${esc(checks.errors.total)}</li>`
      : checks.totals_match
        ? `<li class="pass">✓ Lines add up to the PO total (₹${fmtPaise(checks.calculated_total_paise)})</li>`
        : `<li class="note">• PO total missing, so the sum of lines (₹${fmtPaise(checks.calculated_total_paise)}) could not be compared</li>`);
  } else {
    items.push(`<li class="note">• Line items not checked: this PO has no line items.</li>`);
  }
  items.push(`<li class="pass">✓ Duplicate PO numbers are refused by the database when you save</li>`);
  if (editable) {
    items.push(checks.ok
      ? `<li class="pass"><strong>Ready to submit.</strong></li>`
      : `<li class="fail"><strong>Submit is blocked until the problems above are fixed.</strong></li>`);
  }
  ul.innerHTML = items.join("");
}

function render() {
  const p = po.permissions;
  document.getElementById("title").textContent = po.po_number ? `PO ${po.po_number}` : "Purchase order (no number yet)";
  document.getElementById("status").innerHTML = statusBadge(po.status);
  const methodText = { text_layer: "read from the PDF's text layer", ocr: "read with OCR", manual: "entered by hand" }[po.extraction_method] || po.extraction_method;
  document.getElementById("meta").innerHTML =
    `Created by <strong>${esc(po.created_by)}</strong> · Extraction method: <strong>${esc(po.extraction_method)}</strong> (${esc(methodText)})` +
    (po.has_pdf ? ` · <a href="/api/pos/${po.id}/pdf" target="_blank" rel="noopener">Open original PDF${po.pdf_filename ? " (" + esc(po.pdf_filename) + ")" : ""}</a>` : "");

  HEADER_FIELDS.forEach((f) => {
    const input = document.getElementById(f);
    input.value = f === "po_date" ? showDate(po.po_date) : po[f] ?? "";
    input.readOnly = !p.can_edit;
  });
  const tbody = document.getElementById("lines");
  tbody.innerHTML = "";
  po.line_items.forEach((l) => tbody.appendChild(lineRow(l, p.can_edit)));
  renumber();
  document.getElementById("add-line").hidden = !p.can_edit;

  clearErrors();
  renderChecks(po.checks, p.can_edit);
  if (p.can_edit) showErrors(po.checks.errors, po.checks.line_errors);

  document.getElementById("owner-actions").hidden = !(p.can_edit || p.can_submit);
  document.getElementById("discard").hidden = !p.can_discard;
  document.getElementById("submit").textContent = po.status === "REJECTED" ? "Resubmit for approval" : "Submit for approval";
  document.getElementById("approver-actions").hidden = !p.can_decide;
  const none = document.getElementById("no-actions");
  const anything = p.can_edit || p.can_decide;
  none.hidden = anything;
  if (!anything) {
    none.textContent =
      po.status === "APPROVED" ? "Approved — this purchase order is final and locked." :
      po.status === "SUBMITTED" && po.is_own ? "Submitted — waiting for an approver (you cannot approve your own PO)." :
      po.status === "SUBMITTED" ? "Submitted — waiting for a decision." :
      "No actions available.";
  }

  const hist = document.getElementById("history");
  hist.innerHTML = po.history.length
    ? po.history.map((h) => `<li><strong>${esc(h.action)}</strong> by ${esc(h.by)} · ${esc(showDateTime(h.at))}
        <span class="muted small">(${esc(h.from_status)} → ${esc(h.to_status)})</span>
        ${h.remark ? `<div class="small">${h.action === "REJECT" ? "Reason" : "Remark"}: ${esc(h.remark)}</div>` : ""}</li>`).join("")
    : `<li class="muted">No actions yet. History starts when the PO is submitted.</li>`;
}

async function save({ quiet = false } = {}) {
  clearErrors();
  try {
    const res = await api(`/api/pos/${poId}`, { method: "PUT", json: collect() });
    po = res.po;
    render();
    if (!quiet) { clearBanners(); banner("Saved.", "ok"); }
    return true;
  } catch (err) {
    clearBanners();
    banner(err.error);
    showErrors(err.fields || {}, err.line_errors || {});
    return false;
  }
}

async function act(path, body, okMessage) {
  clearBanners();
  try {
    const res = await api(`/api/pos/${poId}/${path}`, { json: body || {} });
    po = res.po;
    render();
    banner(okMessage, "ok");
  } catch (err) {
    banner(err.error);
    if (err.checks) showErrors(err.checks.errors, err.checks.line_errors);
    if (err.fields) showErrors(err.fields);
  }
}

(async function init() {
  me = await loadMe();
  try {
    po = (await api(`/api/pos/${poId}`)).po;
  } catch (err) {
    document.querySelector("main").innerHTML = `<div class="alert alert-error">${esc(err.error)}</div><p><a href="/">Back to the list</a></p>`;
    return;
  }
  render();

  const once = sessionStorage.getItem(`upload-${poId}`);
  if (once) {
    sessionStorage.removeItem(`upload-${poId}`);
    const { extraction, duplicate } = JSON.parse(once);
    banner(extraction.message, extraction.readable ? (extraction.method === "ocr" ? "warn" : "info") : "warn");
    (extraction.warnings || []).forEach((w) => banner(w, "warn"));
    if (duplicate) {
      banner(duplicate.message + " If this is a re-sent copy, discard this draft.", "error");
      document.getElementById("po_number").value = duplicate.po_number;
      showErrors({ po_number: "This PO number already exists." });
    }
  }

  document.getElementById("add-line").onclick = () => { document.getElementById("lines").appendChild(lineRow({}, true)); renumber(); };
  document.getElementById("save").onclick = () => save();
  document.getElementById("submit").onclick = async () => {
    if (await save({ quiet: true })) await act("submit", {}, "Submitted for approval.");
  };
  document.getElementById("discard").onclick = async () => {
    if (!confirm("Discard this draft? The uploaded PDF will be deleted too.")) return;
    try { await api(`/api/pos/${poId}`, { method: "DELETE" }); window.location.href = "/"; }
    catch (err) { clearBanners(); banner(err.error); }
  };
  document.getElementById("approve").onclick = () => act("approve", { remark: document.getElementById("remark").value }, "Approved.");
  document.getElementById("reject").onclick = () => {
    const reason = document.getElementById("remark").value.trim();
    if (!reason) { clearBanners(); banner("Write a reason before rejecting."); showErrors({ reason: "A reason is required to reject." }); return; }
    act("reject", { reason }, "Rejected. The creator can now fix and resubmit it.");
  };
})();
