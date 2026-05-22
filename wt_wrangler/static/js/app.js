// wt-wrangler frontend — list / search / summon / close Windows Terminal tabs.

/**
 * @typedef {object} Tab
 * @property {number} hwnd      Window handle.
 * @property {number} win_idx   1-based window number.
 * @property {number} tab_idx   Position within the window.
 * @property {string} title     Tab title.
 * @property {boolean} focused  Whether this is the focused tab in its window.
 */

const POLL_MS = 2500;
const LS_FILTER = "wtw.filter";
const LS_LIVE = "wtw.live";

/** @type {Tab[]} */ let tabs = [];
/** @type {Tab[]} */ let view = [];
/** @type {string|null} */ let selKey = null;
let pendingClose = /** @type {Tab|null} */ (null);
let lastSig = "";

const $ = (id) => /** @type {HTMLElement} */ (document.getElementById(id));
const els = {
  list: $("list"), empty: $("empty"), emptyMsg: $("emptyMsg"), count: $("count"),
  search: /** @type {HTMLInputElement} */ ($("search")), clearBtn: $("clearBtn"),
  refreshBtn: $("refreshBtn"), helpBtn: $("helpBtn"),
  autoRefresh: /** @type {HTMLInputElement} */ ($("autoRefresh")),
  confirmModal: $("confirmModal"), confirmBody: $("confirmBody"),
  confirmOk: $("confirmOk"), confirmCancel: $("confirmCancel"),
  helpModal: $("helpModal"), helpClose: $("helpClose"), toast: $("toast"),
};

// --- helpers --------------------------------------------------------------

/**
 * Call the JSON API.
 * @param {string} path
 * @param {object} [body]
 * @returns {Promise<any>}
 */
async function api(path, body) {
  const opt = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const res = await fetch(path, opt);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** @param {Tab} t @returns {string} */
const keyOf = (t) => `${t.hwnd}:${t.tab_idx}`;

/** @param {string} s @returns {string} */
const escHtml = (s) =>
  s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

/** @param {string} s @returns {string} */
const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Sort key ignoring leading status glyphs (✳, spinners). @param {string} t */
function sortKey(t) {
  const s = t.replace(/^[^0-9A-Za-z]+/u, "").toLowerCase();
  return s || t.toLowerCase();
}

/**
 * Highlight filter matches inside an (escaped) title.
 * @param {string} title @param {string} filter @returns {string}
 */
function highlight(title, filter) {
  const safe = escHtml(title);
  if (!filter) return safe;
  try {
    return safe.replace(new RegExp(escRe(escHtml(filter)), "gi"), (m) => `<mark>${m}</mark>`);
  } catch {
    return safe;
  }
}

/**
 * Show a transient toast.
 * @param {string} msg @param {boolean} [isError]
 */
let toastTimer = 0;
function toast(msg, isError = false) {
  els.toast.textContent = msg;
  els.toast.className = `toast${isError ? " err" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => els.toast.classList.add("hidden"), 2200);
}

const modalOpen = () =>
  !els.confirmModal.classList.contains("hidden") || !els.helpModal.classList.contains("hidden");

// --- rendering ------------------------------------------------------------

const ROW_ACTIONS =
  `<div class="tab__actions">` +
  `<button class="act act--summon" data-act="summon" title="Summon (Enter)" aria-label="Summon">` +
  `<svg viewBox="0 0 24 24" width="16" height="16"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M14 4h6v6M20 4l-9 9M19 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4"/></svg>` +
  `</button>` +
  `<button class="act act--close" data-act="close" title="Close (Delete)" aria-label="Close">` +
  `<svg viewBox="0 0 24 24" width="16" height="16"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M6 6l12 12M18 6L6 18"/></svg>` +
  `</button></div>`;

/** @param {Tab} t @param {string} filter @returns {string} */
const titleHtml = (t, filter) => highlight(t.title || "(untitled)", filter);

/** @param {Tab} t @returns {string} */
const metaText = (t) => `window ${t.win_idx} · tab ${t.tab_idx + 1}${t.focused ? " · focused" : ""}`;

/**
 * Patch an existing row in place — no innerHTML rebuild, so the entry
 * animation does not replay (this is what was causing the refresh "flash").
 * @param {HTMLElement} el @param {Tab} t @param {string} filter
 */
function updateRow(el, t, filter) {
  el.className = `tab${t.focused ? " focused" : ""}${keyOf(t) === selKey ? " sel" : ""}`;
  el.querySelector(".tab__dot").title = t.focused ? "Focused tab in its window" : "";
  const titleEl = el.querySelector(".tab__title");
  const html = titleHtml(t, filter);
  if (titleEl.innerHTML !== html) titleEl.innerHTML = html;
  const metaEl = el.querySelector(".tab__meta");
  const meta = metaText(t);
  if (metaEl.textContent !== meta) metaEl.textContent = meta;
}

/** Create a fresh row (these are the only rows that animate in). @param {Tab} t @param {string} filter */
function createRow(t, filter) {
  const el = document.createElement("div");
  el.dataset.key = keyOf(t);
  el.setAttribute("role", "button");
  el.tabIndex = -1;
  el.title = "Summon this tab";
  el.innerHTML =
    `<span class="tab__dot"></span>` +
    `<div class="tab__main"><div class="tab__title"></div><div class="tab__meta"></div></div>` +
    ROW_ACTIONS;
  updateRow(el, t, filter);
  return el;
}

/** Build the filtered + sorted view and reconcile it into the DOM. */
function renderList() {
  const filter = els.search.value.trim().toLowerCase();
  view = tabs
    .filter((t) => !filter || t.title.toLowerCase().includes(filter) || `w${t.win_idx}`.includes(filter))
    .sort((a, b) => sortKey(a.title).localeCompare(sortKey(b.title)));

  els.count.textContent = filter ? `${view.length} / ${tabs.length}` : `${tabs.length} tabs`;
  els.clearBtn.classList.toggle("hidden", !els.search.value);

  if (!view.length) {
    els.list.replaceChildren();
    els.empty.classList.remove("hidden");
    els.emptyMsg.textContent = tabs.length ? "No tabs match your search." : "No Windows Terminal tabs found.";
    return;
  }
  els.empty.classList.add("hidden");
  if (!view.some((t) => keyOf(t) === selKey)) selKey = keyOf(view[0]);

  // Keyed reconcile: reuse + patch existing rows, only create (and animate) new ones.
  const existing = new Map();
  for (const el of els.list.children) existing.set(el.dataset.key, el);
  view.forEach((t, i) => {
    const key = keyOf(t);
    let el = existing.get(key);
    if (el) {
      updateRow(el, t, filter);
      existing.delete(key);
    } else {
      el = createRow(t, filter);
    }
    if (els.list.children[i] !== el) els.list.insertBefore(el, els.list.children[i] || null);
  });
  for (const el of existing.values()) el.remove();
}

/** Update which row is selected without rebuilding the list. @param {string} key */
function setSelection(key) {
  selKey = key;
  for (const el of els.list.children) {
    const on = el.getAttribute("data-key") === key;
    el.classList.toggle("sel", on);
    if (on) el.scrollIntoView({ block: "nearest" });
  }
}

/** @param {number} delta */
function moveSelection(delta) {
  if (!view.length) return;
  let idx = view.findIndex((t) => keyOf(t) === selKey);
  idx = Math.max(0, Math.min(view.length - 1, (idx < 0 ? 0 : idx) + delta));
  setSelection(keyOf(view[idx]));
}

const selectedTab = () => view.find((t) => keyOf(t) === selKey) || null;

// --- data + actions -------------------------------------------------------

/** Fetch tabs and re-render only when the data actually changed. */
async function refresh() {
  try {
    const data = await api("/api/tabs");
    tabs = data.tabs;
    const sig = JSON.stringify(tabs.map((t) => [t.hwnd, t.tab_idx, t.title, t.focused]));
    if (sig !== lastSig) {
      lastSig = sig;
      renderList();
    } else {
      els.count.textContent = els.search.value.trim() ? `${view.length} / ${tabs.length}` : `${tabs.length} tabs`;
    }
  } catch (e) {
    toast(`Could not reach server (${e.message})`, true);
  }
}

/** @param {Tab} t */
async function summon(t) {
  try {
    const { ok } = await api("/api/summon", { hwnd: t.hwnd, tab_idx: t.tab_idx });
    toast(ok ? `Summoned: ${t.title || "tab"}` : "Could not summon that tab", !ok);
    setTimeout(refresh, 250);
  } catch (e) {
    toast(`Summon failed (${e.message})`, true);
  }
}

/** @param {Tab} t */
function askClose(t) {
  pendingClose = t;
  els.confirmBody.textContent = t.title || "(untitled tab)";
  els.confirmModal.classList.remove("hidden");
  els.confirmOk.focus();
}

async function doClose() {
  const t = pendingClose;
  closeModals();
  if (!t) return;
  try {
    const { ok } = await api("/api/close", { hwnd: t.hwnd, tab_idx: t.tab_idx });
    toast(ok ? `Closed: ${t.title || "tab"}` : "Could not close that tab", !ok);
    setTimeout(refresh, 250);
  } catch (e) {
    toast(`Close failed (${e.message})`, true);
  }
}

function closeModals() {
  els.confirmModal.classList.add("hidden");
  els.helpModal.classList.add("hidden");
  pendingClose = null;
}

// --- events ---------------------------------------------------------------

els.list.addEventListener("click", (e) => {
  const row = /** @type {HTMLElement} */ (e.target).closest(".tab");
  if (!row) return;
  const t = view.find((x) => keyOf(x) === row.dataset.key);
  if (!t) return;
  const actBtn = /** @type {HTMLElement} */ (e.target).closest("[data-act]");
  if (actBtn) {
    e.stopPropagation();
    if (actBtn.getAttribute("data-act") === "summon") summon(t);
    else askClose(t);
  } else {
    summon(t);
  }
});

els.list.addEventListener("mousemove", (e) => {
  const row = /** @type {HTMLElement} */ (e.target).closest(".tab");
  if (row && row.getAttribute("data-key") !== selKey) setSelection(row.getAttribute("data-key"));
});

els.search.addEventListener("input", () => {
  localStorage.setItem(LS_FILTER, els.search.value);
  renderList();
});

els.clearBtn.addEventListener("click", () => {
  els.search.value = "";
  localStorage.removeItem(LS_FILTER);
  renderList();
  els.search.focus();
});

els.refreshBtn.addEventListener("click", () => {
  els.refreshBtn.classList.add("spin");
  setTimeout(() => els.refreshBtn.classList.remove("spin"), 600);
  lastSig = "";
  refresh();
});

els.helpBtn.addEventListener("click", () => els.helpModal.classList.remove("hidden"));
els.helpClose.addEventListener("click", closeModals);
els.confirmCancel.addEventListener("click", closeModals);
els.confirmOk.addEventListener("click", doClose);

for (const m of [els.confirmModal, els.helpModal]) {
  m.addEventListener("click", (e) => {
    if (e.target === m) closeModals();
  });
}

els.autoRefresh.addEventListener("change", () => localStorage.setItem(LS_LIVE, els.autoRefresh.checked ? "1" : "0"));

document.addEventListener("keydown", (e) => {
  if (modalOpen()) {
    if (e.key === "Escape") closeModals();
    else if (e.key === "Enter" && !els.confirmModal.classList.contains("hidden")) doClose();
    return;
  }
  switch (e.key) {
    case "ArrowDown": e.preventDefault(); moveSelection(1); break;
    case "ArrowUp": e.preventDefault(); moveSelection(-1); break;
    case "Enter": {
      const t = selectedTab();
      if (t) { e.preventDefault(); summon(t); }
      break;
    }
    case "Delete": {
      const t = selectedTab();
      if (t && els.search.value === "") { e.preventDefault(); askClose(t); }
      break;
    }
    case "Escape":
      if (els.search.value) { els.search.value = ""; localStorage.removeItem(LS_FILTER); renderList(); }
      break;
    case "?":
      if (els.search.value === "") { e.preventDefault(); els.helpModal.classList.remove("hidden"); }
      break;
    case "r": case "R":
      if (els.search.value === "" && !e.ctrlKey && !e.metaKey) { e.preventDefault(); els.refreshBtn.click(); }
      break;
    default:
      if (e.key.length === 1 && document.activeElement !== els.search) els.search.focus();
  }
});

// --- init -----------------------------------------------------------------

function init() {
  els.search.value = localStorage.getItem(LS_FILTER) || "";
  els.autoRefresh.checked = localStorage.getItem(LS_LIVE) !== "0";
  refresh();
  els.search.focus();
  setInterval(() => {
    if (els.autoRefresh.checked && !modalOpen()) refresh();
  }, POLL_MS);
}

init();
