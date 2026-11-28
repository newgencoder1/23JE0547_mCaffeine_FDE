const VIEWS = {
  mine: { label: "My purchase orders", empty: "You have no purchase orders yet. Upload a PDF to start." },
  queue: { label: "Waiting for approval", empty: "Nothing is waiting for a decision right now." },
  decided: { label: "Decided", empty: "No approved or rejected purchase orders yet." },
};

let me;
let current = null;          // the tab being shown
const cache = {};            // view -> items, so tabs and search don't refetch

async function fetchView(view) {
  const { items } = await api(`/api/pos?view=${view}`);
  cache[view] = items;
  return items;
}

// Summary tiles, built from every list this user can see (deduplicated by id).
function renderStats() {
  const all = new Map();
  Object.values(cache).forEach((items) => items.forEach((po) => all.set(po.id, po)));
  const pos = [...all.values()];
  const count = (s) => pos.filter((po) => po.status === s).length;
  const sum = (s) => pos.filter((po) => po.status === s).reduce((a, po) => a + (po.total_paise || 0), 0);
  const tiles = [];
  if (me.is_creator) tiles.push({ cls: "draft", label: "Drafts", value: count("DRAFT"), sub: "Not submitted yet" });
  tiles.push({ cls: "submitted", label: "Awaiting approval", value: count("SUBMITTED"), sub: `₹${fmtPaise(sum("SUBMITTED"))}` });
  tiles.push({ cls: "approved", label: "Approved", value: count("APPROVED"), sub: `₹${fmtPaise(sum("APPROVED"))}` });
  tiles.push({ cls: "rejected", label: "Rejected", value: count("REJECTED"), sub: me.is_creator ? "Fix and resubmit" : "Sent back to creator" });
  document.getElementById("stats").innerHTML = tiles.map((t) => `
    <div class="stat stat-${t.cls}">
      <span class="stat-label">${t.label}</span>
      <span class="stat-value">${t.value}</span>
      <span class="stat-sub">${esc(t.sub)}</span>
    </div>`).join("");
}

function renderList() {
  const list = document.getElementById("list");
  const q = document.getElementById("search").value.trim().toLowerCase();
  const items = (cache[current] || []).filter((po) => !q ||
    [po.po_number, po.vendor_name, po.created_by].some((v) => String(v || "").toLowerCase().includes(q)));

  if (!items.length) {
    list.innerHTML = `<div class="empty">${ICONS.inbox}<p>${q ? "No purchase orders match your search." : VIEWS[current].empty}</p></div>`;
    return;
  }
  const showCreator = current !== "mine";
  list.innerHTML = `<div class="table-wrap"><table class="po-table">
    <thead><tr><th>PO number</th><th>Vendor</th><th class="hide-sm">PO date</th><th class="num">Total (₹)</th>
    <th>Status</th>${showCreator ? "<th class=\"hide-sm\">Created by</th>" : ""}<th class="hide-sm">Updated</th><th></th></tr></thead>
    <tbody>${items.map((po) => `
      <tr class="clickable" data-id="${po.id}" tabindex="0">
        <td class="po-no">${esc(po.po_number) || '<span class="muted">No number yet</span>'}</td>
        <td><div class="vendor"><span class="vendor-mark">${esc(initials(po.vendor_name || "?"))}</span><span>${esc(po.vendor_name) || '<span class="muted">—</span>'}</span></div></td>
        <td class="hide-sm">${esc(showDate(po.po_date)) || '<span class="muted">—</span>'}</td>
        <td class="num strong">${esc(po.total ?? "—")}</td>
        <td>${statusBadge(po.status)}</td>
        ${showCreator ? `<td class="hide-sm">${esc(po.created_by)}${po.is_own ? ' <span class="tag">you</span>' : ""}</td>` : ""}
        <td class="hide-sm small muted">${esc(showDateTime(po.updated_at))}</td>
        <td class="chev">›</td>
      </tr>`).join("")}</tbody></table></div>`;
  list.querySelectorAll("tr.clickable").forEach((tr) => {
    const open = () => (window.location.href = `/po/${tr.dataset.id}`);
    tr.onclick = open;
    tr.onkeydown = (e) => { if (e.key === "Enter") open(); };
  });
}

async function showList(view) {
  current = view;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  const list = document.getElementById("list");
  if (!cache[view]) {
    list.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>`;
    try { await fetchView(view); } catch (err) { flash(list, err.error); return; }
  }
  renderList();
}

// ---- upload (click to browse or drag and drop) ----
function setChosenFile() {
  const file = document.getElementById("file").files[0];
  const zone = document.getElementById("dropzone");
  zone.classList.toggle("has-file", !!file);
  document.getElementById("dz-icon").innerHTML = file ? ICONS.file : ICONS.upload;
  document.getElementById("dz-title").innerHTML = file ? esc(file.name) : "Drop a PO PDF here, or <u>browse</u>";
  document.getElementById("dz-hint").textContent = file
    ? `${(file.size / 1024).toFixed(0)} KB · click to choose a different file`
    : "PDF only, up to 5 MB. Digital PDFs are read automatically; scans open an empty form for you to fill in.";
  document.getElementById("upload-btn").disabled = !file;
}

async function upload(e) {
  e.preventDefault();
  const msg = document.getElementById("msg");
  const file = document.getElementById("file").files[0];
  if (!file) { flash(msg, "Choose a PDF file first."); return; }
  if (file.size > 5 * 1024 * 1024) { flash(msg, "That file is larger than 5 MB."); return; }
  const btn = document.getElementById("upload-btn");
  btn.disabled = true; btn.textContent = "Reading PDF…";
  document.getElementById("dropzone").classList.add("busy");
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await api("/api/pos/upload", { method: "POST", body: form });
    // Pass the one-time extraction/duplicate messages to the PO page.
    sessionStorage.setItem(`upload-${res.po.id}`, JSON.stringify({ extraction: res.extraction, duplicate: res.duplicate || null }));
    window.location.href = `/po/${res.po.id}`;
  } catch (err) {
    flash(msg, err.error);
    btn.disabled = false; btn.textContent = "Upload and read";
    document.getElementById("dropzone").classList.remove("busy");
  }
}

function setupUpload() {
  const zone = document.getElementById("dropzone");
  const input = document.getElementById("file");
  document.getElementById("upload-card").hidden = false;
  document.getElementById("upload-form").onsubmit = upload;
  input.onchange = setChosenFile;
  ["dragenter", "dragover"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.remove("drag"); }));
  zone.addEventListener("drop", (e) => {
    if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; setChosenFile(); }
  });
  setChosenFile();
}

(async function init() {
  me = await loadMe();
  const views = [];
  if (me.is_creator) views.push("mine");
  if (me.is_approver) views.push("queue", "decided");
  document.getElementById("subtitle").textContent =
    me.is_creator && me.is_approver ? "Create your own POs and decide on other people's." :
    me.is_approver ? "Review submitted POs from every creator." :
    "Upload, check and submit your POs for approval.";
  document.getElementById("tabs").innerHTML = views
    .map((v) => `<button data-view="${v}">${VIEWS[v].label}<span class="count" data-count="${v}"></span></button>`).join("");
  document.querySelectorAll("#tabs button").forEach((b) => (b.onclick = () => showList(b.dataset.view)));
  document.getElementById("search").oninput = () => current && renderList();
  if (me.is_creator) setupUpload();
  if (!views.length) return;

  try {
    await Promise.all(views.map(fetchView));
  } catch (err) {
    flash(document.getElementById("msg"), err.error);
  }
  views.forEach((v) => {
    const el = document.querySelector(`[data-count="${v}"]`);
    if (el && cache[v]) el.textContent = cache[v].length;
  });
  renderStats();
  showList(me.is_approver && !me.is_creator ? "queue" : views[0]);
})();
