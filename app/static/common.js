// Shared helpers for all pages. No framework: fetch + DOM.
// The UI only decides what to SHOW; every rule is enforced again by the server.

async function api(path, options = {}) {
  const opts = { credentials: "same-origin", ...options };
  if (opts.json !== undefined) {
    opts.method = opts.method || "POST";
    opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw { status: 0, error: "Can't reach the server. Check your connection and try again." };
  }
  let body = {};
  try { body = await res.json(); } catch (e) { /* non-JSON reply */ }
  if (res.status === 401 && !path.startsWith("/api/login")) {
    window.location.href = "/login";
    throw { status: 401, error: "Please log in." };
  }
  if (!res.ok) {
    const msg = body.error || `Request failed (${res.status}).`;
    throw { ...body, status: res.status, error: body.request_id && res.status >= 500 ? `${msg} (ref ${body.request_id})` : msg };
  }
  return body;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Stored as ISO YYYY-MM-DD, shown as DD-MM-YYYY.
function showDate(iso) {
  if (!iso) return "";
  const [y, m, d] = String(iso).slice(0, 10).split("-");
  return `${d}-${m}-${y}`;
}

function showDateTime(iso) {
  if (!iso) return "";
  const dt = new Date(iso.includes("T") || iso.includes("+") ? iso : iso.replace(" ", "T") + "Z");
  if (isNaN(dt)) return iso;
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(dt.getDate())}-${pad(dt.getMonth() + 1)}-${dt.getFullYear()} ${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
}

function statusBadge(status) {
  return `<span class="badge badge-${esc(status).toLowerCase()}">${esc(status)}</span>`;
}

function roleText(u) {
  const roles = [];
  if (u.is_creator) roles.push("Creator");
  if (u.is_approver) roles.push("Approver");
  return roles.join(" + ");
}

async function loadMe() {
  const { user } = await api("/api/me");
  const bar = document.getElementById("userbar");
  if (bar) {
    bar.innerHTML = `<span>${esc(user.username)} <small>(${esc(roleText(user))})</small></span>
      <button class="link" id="logout">Log out</button>`;
    document.getElementById("logout").onclick = async () => {
      await api("/api/logout", { method: "POST" });
      window.location.href = "/login";
    };
  }
  return user;
}

function flash(el, message, kind = "error") {
  el.innerHTML = message ? `<div class="alert alert-${kind}">${esc(message)}</div>` : "";
}
