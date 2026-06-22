"use strict";

const PEOPLE = ["Zsombor", "Martin", "Lili"];
const view = document.getElementById("view");
const nav = document.getElementById("nav");
const enginePill = document.getElementById("enginePill");

// ---------------- helpers ----------------
const api = {
  async get(p) { const r = await fetch(p); return r.json(); },
  async post(p, body) {
    const r = await fetch(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    return r.json();
  },
  async put(p, body) {
    const r = await fetch(p, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    return r.json();
  },
  async del(p) { return (await fetch(p, { method: "DELETE" })).json(); },
};
const h = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const fmtH = (x) => (x % 1 === 0 ? x.toFixed(0) : x.toFixed(1));

// Format a stored ISO timestamp as "MM.DD - HH:MM" in the viewer's local time.
function fmtDateTime(iso) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}.${p(d.getDate())} - ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// Mirrors ai.py duration detection — true if the text contains minutes/hours.
function hasDuration(text) {
  return /\d+(?:[.,]\d+)?\s*(?:h\b|hr\b|hours?\b|ó[raást]*\b)/i.test(text) ||
         /\d+\s*(?:p|perc|min|minute|m)\b/i.test(text);
}

const ENERGY_CLASS = { green: "b-green", yellow: "b-yellow", red: "b-red" };
const ENERGY_LABEL = { green: "Energizing", yellow: "Neutral", red: "Draining" };
const DECISION_CLASS = {
  "Keep": "b-green", "Delegate ASAP": "b-red", "Automate": "b-accent",
  "Batch": "b-yellow", "Playbook Needed": "b-yellow",
  "Needs New Hire": "b-accent", "Review Later": "b-dim",
};
function badge(cls, txt) { return `<span class="badge ${cls}">${h(txt)}</span>`; }

// ---------------- nav ----------------
const ROUTES = [
  { id: "dashboard", label: "Dashboard", ico: "◧" },
  { sec: "People" },
  { id: "Zsombor", label: "Zsombor", ico: "●" },
  { id: "Martin", label: "Martin", ico: "●" },
  { id: "Lili", label: "Lili", ico: "●" },
  { sec: "" },
  { id: "insights", label: "AI Insights", ico: "✦" },
];

function renderNav() {
  nav.innerHTML = ROUTES.map((r) => {
    if (r.sec !== undefined) return `<div class="nav-section">${h(r.sec)}</div>`;
    return `<div class="nav-item" data-route="${r.id}"><span class="ico">${r.ico}</span>${h(r.label)}</div>`;
  }).join("");
  nav.querySelectorAll(".nav-item").forEach((el) =>
    el.addEventListener("click", () => { location.hash = el.dataset.route; closeSidebar(); }));
}

function setActive(route) {
  nav.querySelectorAll(".nav-item").forEach((el) =>
    el.classList.toggle("active", el.dataset.route === route));
}

// ---------------- router ----------------
async function route() {
  const r = (location.hash.replace("#", "") || "dashboard");
  setActive(r);
  if (PEOPLE.includes(r)) return renderPerson(r);
  if (r === "insights") return renderInsights();
  return renderDashboard();
}

// ============ shared person filter (segmented control) ============
function segmented(id, current) {
  const opts = [["all", "All KALU"], ["Zsombor", "Zsombor"], ["Martin", "Martin"], ["Lili", "Lili"]];
  return `<div class="segmented" id="${id}">${opts.map(([v, l]) =>
    `<button class="seg ${current === v ? "active" : ""}" data-person="${v}">${h(l)}</button>`).join("")}</div>`;
}
function bindSeg(id, cb) {
  document.querySelectorAll(`#${id} .seg`).forEach((b) =>
    b.addEventListener("click", () => cb(b.dataset.person)));
}
const personQS = (p) => (p === "all" ? "" : `?person=${encodeURIComponent(p)}`);

// ============ date-range filter (Meta-style calendar) ============
let dashRange = { from: null, to: null, label: "Teljes időszak" };
let insightRange = { from: null, to: null, label: "Teljes időszak" };

function buildQS(person, range) {
  const parts = [];
  if (person && person !== "all") parts.push("person=" + encodeURIComponent(person));
  if (range && range.from != null) parts.push("from=" + range.from);
  if (range && range.to != null) parts.push("to=" + range.to);
  return parts.length ? "?" + parts.join("&") : "";
}

function dateBtnHTML(id, range) {
  return `<button class="datebtn" id="${id}"><span class="cal-ico">▦</span>${h(range.label)}<span class="caret">▾</span></button>`;
}

const MONTHS_HU = ["Január", "Február", "Március", "Április", "Május", "Június",
  "Július", "Augusztus", "Szeptember", "Október", "November", "December"];
const WD_HU = ["H", "K", "Sze", "Cs", "P", "Szo", "V"];
const _sod = (d) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; };
const _eod = (d) => { const x = new Date(d); x.setHours(23, 59, 59, 999); return x; };
const _sameDay = (a, b) => a && b && a.getFullYear() === b.getFullYear() &&
  a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
const _md = (d) => { const p = (n) => String(n).padStart(2, "0"); return `${p(d.getMonth() + 1)}.${p(d.getDate())}`; };
function _rangeLabel(f, t) {
  if (!f && !t) return "Teljes időszak";
  if (f && t) return _sameDay(f, t) ? _md(f) : `${_md(f)} – ${_md(t)}`;
  return f ? `${_md(f)} –` : `– ${_md(t)}`;
}
function _datePresets() {
  const today = new Date();
  const sub = (n) => { const x = new Date(today); x.setDate(today.getDate() - n); return x; };
  const mStart = new Date(today.getFullYear(), today.getMonth(), 1);
  return [
    ["Ma", today, today], ["Tegnap", sub(1), sub(1)],
    ["Utolsó 7 nap", sub(6), today], ["Utolsó 30 nap", sub(29), today],
    ["Ez a hónap", mStart, today], ["Teljes időszak", null, null],
  ];
}

let _openPop = null;
function _closePop() {
  if (_openPop) {
    _openPop.remove(); _openPop = null;
    document.removeEventListener("mousedown", _outsidePop);
    document.removeEventListener("keydown", _escPop);
  }
}
function _outsidePop(e) {
  if (_openPop && !_openPop.contains(e.target) && !e.target.closest(".datebtn")) _closePop();
}
function _escPop(e) { if (e.key === "Escape") _closePop(); }

function openDatePicker(anchor, current, onApply) {
  _closePop();
  let selFrom = current.from != null ? _sod(new Date(current.from)) : null;
  let selTo = current.to != null ? _sod(new Date(current.to)) : null;
  let presetLabel = (selFrom || selTo) ? null : "Teljes időszak";
  let view = new Date(selFrom || new Date()); view.setDate(1);

  const pop = document.createElement("div");
  pop.className = "datepop";
  document.body.appendChild(pop);
  _openPop = pop;

  function monthHTML(year, month) {
    const startWd = (new Date(year, month, 1).getDay() + 6) % 7;
    const dim = new Date(year, month + 1, 0).getDate();
    let cells = "";
    for (let i = 0; i < startWd; i++) cells += `<div class="cal-cell empty"></div>`;
    for (let day = 1; day <= dim; day++) {
      const d = new Date(year, month, day);
      const cls = ["cal-cell"];
      if (selFrom && selTo && d >= selFrom && d <= selTo) cls.push("in-range");
      if (_sameDay(d, selFrom) || _sameDay(d, selTo)) cls.push("endpoint");
      cells += `<button class="${cls.join(" ")}" data-day="${year}-${month}-${day}">${day}</button>`;
    }
    return `<div class="cal-month"><div class="cal-mhead">${MONTHS_HU[month]} ${year}</div>
      <div class="cal-grid">${WD_HU.map((w) => `<div class="cal-wd">${w}</div>`).join("")}${cells}</div></div>`;
  }

  function render() {
    const y = view.getFullYear(), m = view.getMonth();
    const nxt = new Date(y, m + 1, 1);
    pop.innerHTML =
      `<div class="dp-presets">${_datePresets().map(([lbl], i) =>
        `<button class="dp-preset" data-preset="${i}">${lbl}</button>`).join("")}</div>
      <div class="dp-cal">
        <div class="dp-calhead">
          <button class="dp-nav" data-nav="-1">‹</button>
          <div class="dp-range">${_rangeLabel(selFrom, selTo)}</div>
          <button class="dp-nav" data-nav="1">›</button>
        </div>
        <div class="dp-months">${monthHTML(y, m)}<div class="dp-month2">${monthHTML(nxt.getFullYear(), nxt.getMonth())}</div></div>
        <div class="dp-actions">
          <button class="btn-sm btn-ghost dp-cancel">Mégse</button>
          <button class="btn-sm dp-apply">Alkalmaz</button>
        </div>
      </div>`;
    bind();
    position();
  }

  function bind() {
    pop.querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => {
      const [lbl, f, t] = _datePresets()[+b.dataset.preset];
      selFrom = f ? _sod(f) : null; selTo = t ? _sod(t) : null; presetLabel = lbl;
      if (selFrom) { view = new Date(selFrom); view.setDate(1); }
      render();
    }));
    pop.querySelectorAll("[data-nav]").forEach((b) => b.addEventListener("click", () => {
      view.setMonth(view.getMonth() + Number(b.dataset.nav)); render();
    }));
    pop.querySelectorAll("[data-day]").forEach((b) => b.addEventListener("click", () => {
      const [yy, mm, dd] = b.dataset.day.split("-").map(Number);
      const d = new Date(yy, mm, dd); presetLabel = null;
      if (!selFrom || (selFrom && selTo)) { selFrom = d; selTo = null; }
      else if (d < selFrom) { selFrom = d; }
      else { selTo = d; }
      render();
    }));
    pop.querySelector(".dp-cancel").addEventListener("click", _closePop);
    pop.querySelector(".dp-apply").addEventListener("click", () => {
      const f = selFrom, t = selTo || selFrom;
      const range = (!f && !t)
        ? { from: null, to: null, label: "Teljes időszak" }
        : { from: _sod(f).getTime(), to: _eod(t).getTime(), label: presetLabel || _rangeLabel(f, t) };
      _closePop();
      onApply(range);
    });
  }

  function position() {
    const r = anchor.getBoundingClientRect();
    pop.style.position = "absolute";
    pop.style.top = (r.bottom + window.scrollY + 8) + "px";
    let left = r.right + window.scrollX - pop.offsetWidth;
    if (left < 8) left = 8;
    pop.style.left = left + "px";
  }

  render();
  setTimeout(() => {
    document.addEventListener("mousedown", _outsidePop);
    document.addEventListener("keydown", _escPop);
  }, 0);
}

// ================= DASHBOARD =================
let dashPerson = "all"; // "all" | "Zsombor" | "Martin" | "Lili"

function bindDashFilter() {
  bindSeg("dashFilter", (p) => { dashPerson = p; renderDashboard(); });
  const db = document.getElementById("dashDate");
  if (db) db.addEventListener("click", () =>
    openDatePicker(db, dashRange, (r) => { dashRange = r; renderDashboard(); }));
  document.querySelectorAll("[data-bucket]").forEach((c) =>
    c.addEventListener("click", () => openTaskDrill(c.dataset.bucket)));
}

// Drill-down: which tasks fall into each KPI bucket.
const BUCKETS = {
  delegate: { label: "Delegatable", filter: (t) => t.decision === "Delegate ASAP" },
  automate: { label: "Automatable", filter: (t) => t.decision === "Automate" },
  keep: { label: "Keep with founders", filter: (t) => t.decision === "Keep" },
  batch: { label: "Batchable", filter: (t) => t.decision === "Batch" },
  interrupt: { label: "Interruptions", filter: (t) => t.interrupt },
};

function drillRow(t) {
  return `<div class="drill-row">
    <div class="drill-main">
      <div class="drill-name">${h(t.task_name)}</div>
      <div class="drill-sub">${h(t.person)} · ${badge("b-dim", t.department)} ${badge("b-dim", t.business_value)}
        <span class="dot ${t.energy}"></span> · ${h(fmtDateTime(t.created_at))}</div>
    </div>
    <div class="drill-min">${t.minutes}m</div>
  </div>`;
}

async function openTaskDrill(bucketKey) {
  const meta = BUCKETS[bucketKey];
  if (!meta) return;
  const all = await api.get("/api/tasks" + buildQS(dashPerson, dashRange));
  const tasks = all.filter(meta.filter);
  const totalMin = tasks.reduce((a, t) => a + t.minutes, 0);
  const who = dashPerson === "all" ? "KALU" : dashPerson;

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `<div class="modal">
    <div class="modal-head">
      <div><div class="modal-title">${h(meta.label)}</div>
        <div class="modal-sub">${who} · ${tasks.length} feladat · ${fmtH(totalMin / 60)}h${dashRange.from != null ? ` · ${h(dashRange.label)}` : ""}</div></div>
      <button class="modal-close" title="Bezárás">×</button>
    </div>
    <div class="modal-body">${tasks.length
      ? tasks.map(drillRow).join("")
      : `<div class="empty">Nincs ide sorolt feladat ebben az időszakban.</div>`}</div>
  </div>`;
  document.body.appendChild(overlay);

  const close = () => { overlay.remove(); document.removeEventListener("keydown", esc); };
  const esc = (e) => { if (e.key === "Escape") close(); };
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
  overlay.querySelector(".modal-close").addEventListener("click", close);
  document.addEventListener("keydown", esc);
}

async function renderDashboard() {
  const head = (sub) => `<div class="page-head">
    <div class="head-row"><div class="page-title">Dashboard</div>
      <div class="head-controls">${segmented("dashFilter", dashPerson)}${dateBtnHTML("dashDate", dashRange)}</div></div>
    <div class="page-sub">${sub}</div></div>`;
  view.innerHTML = head("Where founder time goes — and how much we can buy back.") + `<div class="empty">Loading…</div>`;
  bindDashFilter();

  const m = await api.get("/api/dashboard" + buildQS(dashPerson, dashRange));
  const who = dashPerson === "all" ? "KALU" : dashPerson;

  if (!m.task_count) {
    view.innerHTML = head(`${who} · no tasks yet`) +
      `<div class="card"><div class="empty">No tasks logged for ${h(who)} yet. Open their page and dump a few tasks.</div></div>`;
    bindDashFilter();
    return;
  }

  const kpi = (val, unit, label, cls = "", icon = "", bucket = "") =>
    `<div class="card kpi ${cls}${bucket ? " kpi-clickable" : ""}"${bucket ? ` data-bucket="${bucket}"` : ""}>${icon ? `<span class="kpi-icon">${icon}</span>` : ""}
      <div><span class="kpi-val">${val}</span> <span class="kpi-unit">${unit}</span></div>
      <div class="kpi-label">${label}${bucket ? `<span class="kpi-drill">megnézem ↗</span>` : ""}</div></div>`;

  view.innerHTML =
    head(`${who} · ${m.task_count} tasks logged · ${fmtH(m.total_hours)}h recorded`) + `
    <div class="grid kpis">
      ${kpi(fmtH(m.monthly_buyback_hours), "h/mo", "Estimated buy-back / month", "hero", "✦")}
      ${kpi(fmtH(m.delegatable_hours), "h", "Delegatable", "", "→", "delegate")}
      ${kpi(fmtH(m.automatable_hours), "h", "Automatable", "", "⚙", "automate")}
      ${kpi(fmtH(m.founder_hours), "h", "Keep with founders", "", "★", "keep")}
    </div>
    <div class="grid kpis">
      ${kpi(fmtH(m.total_hours), "h", "Total recorded", "", "")}
      ${kpi(fmtH(m.batchable_hours), "h", "Batchable", "", "▦", "batch")}
      ${kpi(m.interrupt_count, "", "Interruptions", "", "!", "interrupt")}
      ${kpi(fmtH(m.focus_loss_hours), "h", "Estimated focus loss", "", "")}
    </div>

    <div class="grid cols-2">
      ${barCard("Time by department", m.by_department, "min")}
      ${barCard("Decision split", m.by_decision, "min")}
    </div>

    <div class="grid cols-2" style="margin-top:14px">
      ${energyCard(m.by_energy)}
      ${dripCard(m.by_drip)}
    </div>

    <div class="grid cols-2" style="margin-top:14px">
      ${drainsCard(m.top_drains)}
      ${listCard("Top tasks to delegate", m.top_delegate, "→")}
    </div>

    <div class="grid cols-2" style="margin-top:14px">
      ${listCard("Top automation opportunities", m.top_automate, "⚙")}
      ${rolesCard(m.missing_roles)}
    </div>`;
  bindDashFilter();
}

function barCard(title, obj, unit) {
  const entries = Object.entries(obj);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  const rows = entries.map(([k, v]) =>
    `<div class="bar-row"><div class="bar-label">${h(k)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(v / max * 100).toFixed(1)}%"></div></div>
      <div class="bar-val">${fmtH(v / 60)}h</div></div>`).join("");
  return `<div class="card"><div class="card-title">${h(title)}</div>
    <div class="bars">${rows || `<div class="empty">—</div>`}</div></div>`;
}

function energyCard(obj) {
  const total = Object.values(obj).reduce((a, b) => a + b, 0) || 1;
  const order = ["green", "yellow", "red"];
  const rows = order.filter((k) => obj[k]).map((k) =>
    `<div class="bar-row"><div class="bar-label"><span class="dot ${k}"></span> ${ENERGY_LABEL[k]}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(obj[k] / total * 100).toFixed(1)}%;background:var(--${k})"></div></div>
      <div class="bar-val">${Math.round(obj[k] / total * 100)}%</div></div>`).join("");
  return `<div class="card"><div class="card-title">Energy balance</div><div class="bars">${rows || `<div class="empty">—</div>`}</div></div>`;
}

function dripCard(obj) {
  return barCard("DRIP framework", obj, "min");
}

function drainsCard(drains) {
  const rows = drains.map((d) =>
    `<div class="row"><div class="r-main"><div class="r-name">${h(d.name)}</div>
      <div class="r-sub">${d.count}× · ${badgeInline(d.energy)} ${h(d.decision)}</div></div>
      <div class="r-min">${fmtH(d.minutes / 60)}h</div></div>`).join("");
  return `<div class="card"><div class="card-title">Top time drains</div>${rows || `<div class="empty">—</div>`}</div>`;
}
function badgeInline(energy) {
  return `<span class="dot ${energy}"></span>`;
}

function listCard(title, items, ico) {
  const rows = (items || []).map((t) =>
    `<div class="row"><div class="r-main"><div class="r-name">${h(t.task_name)}</div>
      <div class="r-sub">${h(t.person)}${t.recommended_owner ? ` · → ${h(t.recommended_owner)}` : ""}</div></div>
      <div class="r-min">${t.minutes}m</div></div>`).join("");
  return `<div class="card"><div class="card-title">${h(title)}</div>${rows || `<div class="empty">Nothing here yet</div>`}</div>`;
}

function rolesCard(roles) {
  const rows = (roles || []).map((r) =>
    `<div class="hire-card"><div class="hire-num">${r.priority}</div>
      <div style="flex:1"><div class="hire-role">${h(r.role)}</div><div class="hire-cover">${h(r.covers)}</div></div>
      <div class="hire-hours">${fmtH(r.weekly_hours)}h/wk</div></div>`).join("");
  return `<div class="card"><div class="card-title">Missing positions</div>${rows || `<div class="empty">No clear role gaps yet</div>`}</div>`;
}

// ================= PERSON PAGE =================
async function renderPerson(person) {
  view.innerHTML = `
    <div class="add-wrap">
      <div class="page-head"><div class="page-title">Add a task</div>
        <div class="page-sub">${h(person)} · dump it fast, the AI handles the rest.</div></div>
      <form class="add-form" id="addForm">
        <input class="add-input" id="taskInput" autocomplete="off"
          placeholder="Feladat amivel foglalkoztál - Amennyi időt igénybe vett" />
        <button class="btn" type="submit" id="saveBtn">Save</button>
      </form>
      <div class="add-error" id="addError" hidden></div>
      <div class="add-hint">Examples: <em>KPMG grafika check - 10p</em> · <em>Lilinek TikTok kód - 2p</em> · <em>Dáviddal meeting - 25p</em></div>
      <div class="tasklist">
        <div class="tasklist-head"><div class="card-title" style="margin:0">Recent tasks</div>
          <div class="meta" id="personMeta"></div></div>
        <div id="taskList"></div>
      </div>
    </div>`;

  const input = document.getElementById("taskInput");
  const form = document.getElementById("addForm");
  const saveBtn = document.getElementById("saveBtn");
  const listEl = document.getElementById("taskList");
  const errEl = document.getElementById("addError");
  input.focus();

  const NO_TIME_MSG = "Add meg mennyi időt töltöttél a feladattal! (pl. „- 10p”)";
  function showError(msg) {
    errEl.textContent = msg || NO_TIME_MSG;
    errEl.hidden = false;
    input.classList.add("input-error");
  }
  function hideError() {
    errEl.hidden = true;
    errEl.textContent = "";
    input.classList.remove("input-error");
  }
  input.addEventListener("input", hideError);

  async function load() {
    const tasks = await api.get(`/api/tasks?person=${encodeURIComponent(person)}`);
    document.getElementById("personMeta").textContent =
      tasks.length ? `${tasks.length} tasks · ${fmtH(tasks.reduce((a, t) => a + t.minutes, 0) / 60)}h` : "";
    listEl.innerHTML = tasks.length ? tasks.map(taskCard).join("") : `<div class="empty">No tasks yet.</div>`;
    bindDeletes(listEl, load);
    bindEdits(listEl, load);
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    hideError();
    if (!text) return;
    // require a duration before saving (instant client-side check)
    if (!hasDuration(text)) { showError(); return; }
    saveBtn.disabled = true;
    // optimistic "analyzing" card
    listEl.insertAdjacentHTML("afterbegin",
      `<div class="task-card" id="pending"><div class="task-top"><div class="task-name">${h(text)}</div></div>
        <div class="analyzing" style="margin-top:10px"><span class="spinner"></span> AI analyzing…</div></div>`);
    input.value = "";
    try {
      const res = await api.post("/api/tasks", { person, text });
      if (res && res.error) {       // server backstop (e.g. no duration)
        input.value = text;
        showError(res.error);
      }
    } finally {
      saveBtn.disabled = false;
      await load();
      input.focus();
    }
  });

  load();
}

function taskCard(t) {
  const recs = (t.recommendations || []).map((r) => `<li>${h(r)}</li>`).join("");
  const flags = [];
  if (t.needs_clarification) flags.push(badge("b-yellow", "⚠ Pontosítható"));
  if (t.interrupt) flags.push(badge("b-red", "Interrupt"));
  if (t.automatable) flags.push(badge("b-accent", "Automatable"));
  if (t.playbook_needed) flags.push(badge("b-yellow", "SOP needed"));
  const clarify = t.needs_clarification && t.clarification_question
    ? `<div class="task-clarify">
         <span class="clarify-q">${h(t.clarification_question)}</span>
         <button class="task-clarify-btn" data-edit="${t.id}" data-raw="${h(t.raw_input)}">Pontosítom</button>
       </div>` : "";
  return `<div class="task-card${t.needs_clarification ? " needs-clarify" : ""}">
    <div class="task-top">
      <div class="task-name">${h(t.task_name)}</div>
      <div class="task-min">${t.minutes}m</div>
      <button class="task-edit" data-edit="${t.id}" data-raw="${h(t.raw_input)}" title="Szerkesztés">✎</button>
      <button class="task-del" data-del="${t.id}" title="Delete">×</button>
    </div>
    <div class="task-tags">
      ${badge("b-dim", t.department)}
      ${badge("b-dim", t.business_value)}
      ${badge(ENERGY_CLASS[t.energy] || "b-dim", ENERGY_LABEL[t.energy] || t.energy)}
      ${badge(DECISION_CLASS[t.decision] || "b-dim", t.decision)}
      ${badge("b-dim", t.drip)}
      ${flags.join("")}
    </div>
    ${clarify}
    ${recs ? `<div class="task-recs"><div class="rt">Buy-back moves · owner: ${h(t.recommended_owner)}</div><ul>${recs}</ul></div>` : ""}
    <div class="task-time">${h(fmtDateTime(t.created_at))}</div>
  </div>`;
}

function bindDeletes(scope, reload) {
  scope.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      await api.del(`/api/tasks/${b.dataset.del}`);
      reload();
    }));
}

const EDIT_NO_TIME = "Add meg mennyi időt töltöttél a feladattal! (pl. „- 10p”)";

// Turn a task card into an inline editor; on save the AI re-analyzes the text.
function enterEditMode(card, id, raw, reload) {
  card.innerHTML =
    `<input class="edit-input" value="${h(raw)}" />
     <div class="add-error edit-err" hidden></div>
     <div class="edit-actions">
       <button class="btn-sm edit-save">Mentés</button>
       <button class="btn-sm btn-ghost edit-cancel">Mégse</button>
     </div>`;
  const inp = card.querySelector(".edit-input");
  const err = card.querySelector(".edit-err");
  inp.focus();
  inp.setSelectionRange(inp.value.length, inp.value.length);
  const showErr = () => { err.textContent = EDIT_NO_TIME; err.hidden = false; inp.classList.add("input-error"); };
  const hideErr = () => { err.hidden = true; err.textContent = ""; inp.classList.remove("input-error"); };
  inp.addEventListener("input", hideErr);
  card.querySelector(".edit-cancel").addEventListener("click", reload);
  const save = async () => {
    const text = inp.value.trim();
    hideErr();
    if (!text) return;
    if (!hasDuration(text)) { showErr(); return; }
    card.innerHTML = `<div class="analyzing"><span class="spinner"></span> AI újraelemzés…</div>`;
    const res = await api.put(`/api/tasks/${id}`, { text });
    if (res && res.error) { enterEditMode(card, id, text, reload); card.querySelector(".edit-err").textContent = res.error; card.querySelector(".edit-err").hidden = false; }
    else reload();
  };
  card.querySelector(".edit-save").addEventListener("click", save);
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); save(); }
    else if (e.key === "Escape") reload();
  });
}

function bindEdits(scope, reload) {
  scope.querySelectorAll("[data-edit]").forEach((b) =>
    b.addEventListener("click", () =>
      enterEditMode(b.closest(".task-card"), b.dataset.edit, b.dataset.raw, reload)));
}

// ================= AI INSIGHTS =================
let insightPerson = "all";
function bindInsFilter() {
  bindSeg("insFilter", (p) => { insightPerson = p; renderInsights(); });
  const db = document.getElementById("insDate");
  if (db) db.addEventListener("click", () =>
    openDatePicker(db, insightRange, (r) => { insightRange = r; renderInsights(); }));
}

async function renderInsights() {
  const head = (sub) => `<div class="page-head">
    <div class="head-row"><div class="page-title">AI Insights</div>
      <div class="head-controls">${segmented("insFilter", insightPerson)}${dateBtnHTML("insDate", insightRange)}</div></div>
    <div class="page-sub">${sub}</div></div>`;
  view.innerHTML = head("Executive summary") + `<div class="empty">Loading…</div>`;
  bindInsFilter();

  const i = await api.get("/api/insights" + buildQS(insightPerson, insightRange));
  const m = i.metrics;
  const who = insightPerson === "all" ? "the founders are" : insightPerson + " is";
  const whoShort = insightPerson === "all" ? "KALU" : insightPerson;
  if (!m.task_count) {
    view.innerHTML = head(`${whoShort} · no tasks yet`) +
      `<div class="card"><div class="empty">No tasks logged for ${h(whoShort)} yet — insights appear as the engine learns the patterns.</div></div>`;
    bindInsFilter();
    return;
  }

  const deptList = i.department_pct.map((d) =>
    `<div class="bar-row"><div class="bar-label">${h(d.label)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${d.pct}%"></div></div>
      <div class="bar-val">${d.pct}%</div></div>`).join("");

  const hireBlock = (hire) => hire ? `<div class="hire-card"><div class="hire-num">${hire.priority}</div>
    <div style="flex:1"><div class="hire-role">${h(hire.role)}</div><div class="hire-cover">${h(hire.covers)}</div></div>
    <div class="hire-hours">${fmtH(hire.monthly_hours)}h/mo</div></div>` : "";

  const sop = (i.sop_opportunities || []).map((s) => `<li>${h(s)}</li>`).join("");
  const auto = (i.automation_opportunities || []).map((s) => `<li>${h(s)}</li>`).join("");

  view.innerHTML =
    head(`Executive summary · ${whoShort} · ${m.task_count} tasks analyzed`) + `
    <div class="card" style="margin-bottom:14px">
      <div class="insight-lead">
        This snapshot, ${who} spending <b>${fmtH(m.total_hours)} hours</b> on logged work.
        About <b>${fmtH(m.delegatable_hours)}h</b> looks delegatable and <b>${fmtH(m.automatable_hours)}h</b> automatable —
        with <b>${m.interrupt_count} interruptions</b> costing an estimated <b>${fmtH(m.focus_loss_hours)}h</b> of focus.
        Buying it back could free roughly <b>${fmtH(m.monthly_buyback_hours)} hours / month</b>.
      </div>
    </div>

    <div class="grid cols-2">
      <div class="card"><div class="card-title">Where the time goes</div><div class="bars">${deptList}</div></div>
      <div class="card"><div class="card-title">Recommended hires</div>
        ${hireBlock(i.first_hire) || `<div class="empty">No clear role gap yet</div>`}
        ${hireBlock(i.second_hire)}
      </div>
    </div>

    <div class="grid cols-2" style="margin-top:14px">
      <div class="card"><div class="card-title">Top SOP opportunities</div>
        ${sop ? `<ul class="task-recs"><div style="display:none"></div>${sop}</ul>` : `<div class="empty">—</div>`}</div>
      <div class="card"><div class="card-title">Top automation opportunities</div>
        ${auto ? `<ul class="task-recs">${auto}</ul>` : `<div class="empty">—</div>`}</div>
    </div>

    <div class="card" style="margin-top:14px">
      <div class="card-title">Biggest time drains (pattern recognition)</div>
      ${(i.top_drains || []).map((d) => `<div class="row"><div class="r-main">
        <div class="r-name">${h(d.name)}</div><div class="r-sub">${d.count}× logged · ${h(d.decision)}</div></div>
        <div class="r-min">${fmtH(d.minutes / 60)}h</div></div>`).join("") || `<div class="empty">—</div>`}
    </div>`;

  // restyle plain ULs in insight cards
  view.querySelectorAll("ul.task-recs").forEach((ul) => {
    ul.style.listStyle = "none";
    ul.querySelectorAll("li").forEach((li) => {
      li.style.cssText = "font-size:13.5px;color:var(--text-dim);padding:6px 0 6px 16px;position:relative;border-bottom:1px solid var(--border-soft)";
      li.insertAdjacentHTML("afterbegin", `<span style="position:absolute;left:0;color:var(--accent-ink)">→</span>`);
    });
  });
  bindInsFilter();
}

// ---------------- sidebar (mobile) ----------------
const sidebar = document.querySelector(".sidebar");
document.getElementById("menuBtn").addEventListener("click", () => sidebar.classList.toggle("open"));
function closeSidebar() { sidebar.classList.remove("open"); }

// ---------------- boot ----------------
async function boot() {
  renderNav();
  try {
    const m = await api.get("/api/dashboard");
    enginePill.textContent = m.engine === "ai" ? "Claude AI" : "Heuristic engine";
    enginePill.classList.toggle("heuristic", m.engine !== "ai");
  } catch (e) { enginePill.textContent = "—"; }
  window.addEventListener("hashchange", route);
  route();
}
boot();
