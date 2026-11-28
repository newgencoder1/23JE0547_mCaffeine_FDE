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

// Integer paise -> "1,24,500.00" (Indian grouping). Display only; no floats involved.
function fmtPaise(p) {
  if (p === null || p === undefined) return "";
  const rupees = Math.floor(Math.abs(p) / 100).toLocaleString("en-IN");
  return `${p < 0 ? "-" : ""}${rupees}.${String(Math.abs(p) % 100).padStart(2, "0")}`;
}

function initials(name) {
  return String(name || "?").replace(/[^a-z0-9]/gi, "").slice(0, 2).toUpperCase() || "?";
}

// Small inline icons (stroke = currentColor), so no icon library is needed.
const ICONS = {
  upload: '<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/></svg>',
  file: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>',
  inbox: '<svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5h13L22 12v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z"/></svg>',
  lock: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
  logout: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg>',
};

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
    bar.innerHTML = `<div class="user-chip">
        <span class="avatar">${esc(initials(user.username))}</span>
        <span class="user-text"><strong>${esc(user.username)}</strong><small>${esc(roleText(user))}</small></span>
      </div>
      <button class="ghost-btn" id="logout" title="Log out">${ICONS.logout}<span>Log out</span></button>`;
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
