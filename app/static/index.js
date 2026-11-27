const VIEWS = {
  mine: { label: "My purchase orders", empty: "You have no purchase orders yet. Upload a PDF to start." },
  queue: { label: "Waiting for approval", empty: "Nothing is waiting for a decision." },
  decided: { label: "Decided", empty: "No approved or rejected purchase orders yet." },
};

let me;

async function showList(view) {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  const list = document.getElementById("list");
  list.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    const { items } = await api(`/api/pos?view=${view}`);
    if (!items.length) { list.innerHTML = `<p class="muted">${VIEWS[view].empty}</p>`; return; }
    list.innerHTML = `<table>
      <thead><tr><th>PO number</th><th>Date</th><th>Vendor</th><th class="num">Total (₹)</th>
      <th>Status</th>${view === "mine" ? "" : "<th>Created by</th>"}<th>Updated</th></tr></thead>
      <tbody>${items.map((po) => `
        <tr class="clickable" data-id="${po.id}">
          <td>${esc(po.po_number) || '<span class="muted">(no number yet)</span>'}</td>
          <td>${esc(showDate(po.po_date))}</td>
          <td>${esc(po.vendor_name)}</td>
          <td class="num">${esc(po.total ?? "")}</td>
          <td>${statusBadge(po.status)}</td>
          ${view === "mine" ? "" : `<td>${esc(po.created_by)}${po.is_own ? ' <small class="muted">(you — another approver must decide)</small>' : ""}</td>`}
          <td class="small muted">${esc(showDateTime(po.updated_at))}</td>
        </tr>`).join("")}</tbody></table>`;
    list.querySelectorAll("tr.clickable").forEach((tr) => (tr.onclick = () => (window.location.href = `/po/${tr.dataset.id}`)));
  } catch (err) {
    flash(list, err.error);
  }
}

async function upload(e) {
  e.preventDefault();
  const msg = document.getElementById("msg");
  const file = document.getElementById("file").files[0];
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) { flash(msg, "That file is larger than 5 MB."); return; }
  const btn = document.getElementById("upload-btn");
  btn.disabled = true; btn.textContent = "Reading PDF…";
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
  }
}

(async function init() {
  me = await loadMe();
  const views = [];
  if (me.is_creator) views.push("mine");
  if (me.is_approver) views.push("queue", "decided");
  document.getElementById("tabs").innerHTML = views
    .map((v) => `<button data-view="${v}">${VIEWS[v].label}</button>`).join("");
  document.querySelectorAll("#tabs button").forEach((b) => (b.onclick = () => showList(b.dataset.view)));
  if (me.is_creator) {
    document.getElementById("upload-card").hidden = false;
    document.getElementById("upload-form").onsubmit = upload;
  }
  if (views.length) showList(me.is_approver && !me.is_creator ? "queue" : views[0]);
})();
