/* Cell Qualification Cockpit — vanilla JS + hand-rolled SVG charts. */

"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const state = { data: null, tab: "fleet", fleet: "qual", filter: null, selected: null,
                search: "", sortKey: null, sortDir: 1, showRef: false, queue: null };
const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- theme: light / dark / system, persisted ---------- */

const THEME_ORDER = ["system", "light", "dark"];
const THEME_GLYPH = { system: "◐", light: "○", dark: "●" };

function applyTheme(theme, rerender = true) {
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  localStorage.setItem("cockpit-theme", theme);
  const btn = document.getElementById("theme-toggle");
  btn.textContent = THEME_GLYPH[theme];
  btn.title = `Theme: ${theme}`;
  // SVG marks bake in resolved token colors, so views re-render on change
  if (rerender && state.data) {
    renderTally();
    renderQueueCards();
    renderFleet();
    renderGates();
    if (state.selected) select(state.selected);
    else renderEmptyInspector();
  }
}

document.getElementById("theme-toggle").addEventListener("click", () => {
  const cur = localStorage.getItem("cockpit-theme") || "system";
  applyTheme(THEME_ORDER[(THEME_ORDER.indexOf(cur) + 1) % THEME_ORDER.length]);
});
applyTheme(localStorage.getItem("cockpit-theme") || "system", false);
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if ((localStorage.getItem("cockpit-theme") || "system") === "system") applyTheme("system");
});


/* ---------- the arrival moment: what is this app? ---------- */

function showWelcome() {
  if (document.querySelector(".welcome-scrim")) return;
  const scrim = html("div", "welcome-scrim", document.body);
  const card = html("div", "welcome-card", scrim);
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-modal", "true");
  html("div", "welcome-mark", card);
  html("h2", "", card).textContent = "Call battery qualification months early.";
  const lead = html("p", "welcome-lead", card);
  lead.textContent = "Every cell here must survive 700 charge\u2013discharge cycles to qualify \u2014 "
    + "months of continuous testing. Hectocycle reads just the first 100 cycles and tells you which "
    + "cells you can already call, and how sure it is allowed to be. This demo runs on 202 cells "
    + "from three public aging studies; every verdict is real model output, scored against ground truth.";
  const outcomes = html("div", "welcome-outcomes", card);
  for (const [v, txt] of [
    ["pass", "call it now \u2014 the cell comes off the test channel"],
    ["keep-testing", "the honest answer when 100 cycles can\u2019t separate it from the spec"],
    ["out-of-envelope", "data the model wasn\u2019t trained for \u2014 it refuses to guess"],
  ]) {
    const row = html("div", "teach-outcome", outcomes);
    row.appendChild(verdictChip(v));
    html("span", "", row).textContent = txt;
  }
  const actions = html("div", "welcome-actions", card);
  const go = html("button", "btn-primary", actions);
  go.textContent = "See a worked example \u2192";
  const skip = html("button", "btn-quiet", actions);
  skip.textContent = "Explore on my own";
  const tryBtn = html("button", "btn-quiet", actions);
  tryBtn.textContent = "Try your own CSV";
  tryBtn.addEventListener("click", () => {
    localStorage.setItem("hectocycle-welcomed", "1");
    scrim.remove();
    document.querySelector('.tab[data-tab="try"]').click();
  });
  const dismiss = (openDemo) => {
    localStorage.setItem("hectocycle-welcomed", "1");
    scrim.remove();
    if (openDemo && state.data) {
      const demo = state.data.qual.cells.find((c) => c.verdict === "keep-testing") || state.data.qual.cells[0];
      select(demo.id);
      document.querySelector(`.fleet tbody tr[data-id="${demo.id}"]`)?.scrollIntoView({ block: "center" });
    }
  };
  go.addEventListener("click", () => dismiss(true));
  skip.addEventListener("click", () => dismiss(false));
  scrim.addEventListener("click", (e) => { if (e.target === scrim) dismiss(false); });
  go.focus();
}

document.getElementById("help-btn").addEventListener("click", showWelcome);

/* count a numeric readout up from zero — the instrument boot moment */
function countUp(node, target, suffix = "", dur = 900) {
  if (REDUCED) { node.textContent = `${target}${suffix}`; return; }
  const t0 = performance.now();
  (function tick(now) {
    const k = Math.min((now - t0) / dur, 1);
    const eased = 1 - Math.pow(1 - k, 3);
    node.textContent = `${Math.round(target * eased)}${suffix}`;
    if (k < 1) requestAnimationFrame(tick);
  })(t0);
}

/* draw line-chart paths in by animating dash offset, staggered per series */
function drawIn(paths) {
  if (REDUCED) return;
  requestAnimationFrame(() => {
    paths.forEach((p, i) => {
      let len;
      try { len = p.getTotalLength(); } catch { return; }
      p.style.strokeDasharray = `${len}`;
      p.style.strokeDashoffset = `${len}`;
      p.getBoundingClientRect();
      p.style.transition = `stroke-dashoffset 0.7s cubic-bezier(0.3, 0.6, 0.3, 1) ${i * 0.12}s`;
      p.style.strokeDashoffset = "0";
      p.addEventListener("transitionend", () => { p.style.strokeDasharray = "none"; }, { once: true });
    });
  });
}

/* ---------- tiny SVG helpers ---------- */

function el(tag, attrs = {}, parent = null) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

function html(tag, cls = "", parent = null) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (parent) parent.appendChild(node);
  return node;
}

const fmt = (v, d = 2) => (v == null || Number.isNaN(v) ? "–" : (+v).toFixed(d));

/* drop logging glitches (zero-capacity first cycles, dropout spikes) */
function cleanFade(fade) {
  const med = [...fade.qd].sort((a, b) => a - b)[Math.floor(fade.qd.length / 2)];
  const keep = fade.qd.map((q) => q > 0.5 * med);
  return {
    cycle: fade.cycle.filter((_, i) => keep[i]),
    qd: fade.qd.filter((_, i) => keep[i]),
  };
}

/* ---------- the verdict bracket (signature element) ---------- */

function verdictBracket(cell, { w = 116, h = 18, big = false } = {}) {
  if (big) { w = 380; h = 40; }
  const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, role: "img",
    "aria-label": `P(pass) ${cell.p_pass}` + (cell.p_lo != null ? `, interval ${cell.p_lo} to ${cell.p_hi}` : "") });
  if (big) svg.setAttribute("class", "bracket-big");
  else { svg.setAttribute("width", w); svg.setAttribute("height", h); }
  const midY = h / 2, x0 = 2, x1 = w - 2;
  const X = (p) => x0 + p * (x1 - x0);
  const colors = { pass: css("--good"), fail: css("--critical"), "keep-testing": css("--warning"), train: css("--muted") };
  const c = colors[cell.verdict] || css("--muted");

  el("line", { x1: x0, y1: midY, x2: x1, y2: midY, stroke: css("--grid"),
    "stroke-width": big ? 2 : 1.5, "stroke-linecap": "round" }, svg);
  // decision notch at 0.5
  el("line", { x1: X(0.5), y1: midY - (big ? 9 : 5), x2: X(0.5), y2: midY + (big ? 9 : 5),
    stroke: css("--baseline"), "stroke-width": big ? 2 : 1.5, "stroke-linecap": "round" }, svg);

  const anim = big ? " bracket-band" : "";
  if (cell.p_lo != null) {
    const bh = big ? 8 : 4;
    el("rect", { x: X(cell.p_lo), y: midY - bh / 2, width: Math.max(X(cell.p_hi) - X(cell.p_lo), 1.5),
      height: bh, rx: bh / 2, fill: c, opacity: 0.4, class: anim.trim() }, svg);
    for (const p of [cell.p_lo, cell.p_hi]) {
      el("line", { x1: X(p), y1: midY - bh, x2: X(p), y2: midY + bh, stroke: c,
        "stroke-width": big ? 2.5 : 1.5, "stroke-linecap": "round",
        class: big ? "bracket-tick" : "" }, svg);
    }
  }
  el("line", { x1: X(cell.p_pass), y1: midY - (big ? 12 : 6), x2: X(cell.p_pass), y2: midY + (big ? 12 : 6),
    stroke: css("--ink"), "stroke-width": big ? 3 : 2, "stroke-linecap": "round",
    class: big ? "bracket-tick" : "" }, svg);

  if (big) {
    for (const [p, anchor] of [[0, "start"], [0.5, "middle"], [1, "end"]]) {
      const t = el("text", { x: X(p), y: h - 1, "text-anchor": anchor, class: "axis-label" }, svg);
      t.textContent = p === 0.5 ? "0.5 — decision line" : String(p);
    }
  }
  return svg;
}

function verdictChip(verdict) {
  // non-decisions stay quiet: train cells get plain muted text, not a pill,
  // so the verdicts that demand action carry all the color on the page
  const chip = html("span", verdict === "train" ? "verdict-quiet" : `verdict-chip ${verdict}`);
  chip.textContent = { pass: "✓ PASS", fail: "✗ FAIL", "keep-testing": "◌ KEEP TESTING",
    train: "train", "out-of-envelope": "⊘ OUT OF ENVELOPE" }[verdict] || verdict;
  chip.title = {
    pass: "Interval clears the 0.5 decision line — callable now; the cell can come off the cycler.",
    fail: "Interval clears the decision line on the fail side — reject early.",
    "keep-testing": "Interval straddles the decision line — the early signal can't separate this cell from the spec threshold yet.",
    train: "Training-split cell: it taught the model, so it gets no verdict.",
    "out-of-envelope": "An input feature is outside the training range — the model refuses rather than extrapolate.",
  }[verdict] || "";
  return chip;
}

/* ---------- sparkline ---------- */

function sparkline(fadeRaw, w = 78, h = 22) {
  const fade = cleanFade(fadeRaw);
  const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, width: w, height: h, "aria-hidden": "true" });
  const xs = fade.cycle, ys = fade.qd;
  const xmin = xs[0], xmax = xs[xs.length - 1];
  const ymin = Math.min(...ys), ymax = Math.max(...ys);
  const X = (x) => 1 + (x - xmin) / (xmax - xmin || 1) * (w - 2);
  const Y = (y) => h - 2 - (y - ymin) / (ymax - ymin || 1) * (h - 4);
  const d = xs.map((x, i) => `${i ? "L" : "M"}${X(x).toFixed(1)},${Y(ys[i]).toFixed(1)}`).join("");
  el("path", { d, fill: "none", stroke: css("--ink-2"), "stroke-width": 1.4,
    "stroke-linecap": "round", "stroke-linejoin": "round" }, svg);
  return svg;
}

/* ---------- line chart with crosshair hover ---------- */

let _clipSeq = 0;

function lineChart({ series, w = 430, h = 190, xlabel = "", ylabel = "", refX = [], refY = [],
                     ylim = null, yfmt = (v) => fmt(v, 2), xfmt = (v) => String(Math.round(v)) }) {
  const pad = { l: 46, r: 14, t: 20, b: 26 };
  const wrap = html("div", "chart");
  const svg = el("svg", { viewBox: `0 0 ${w} ${h}` }, null);
  wrap.appendChild(svg);

  const xs = series.flatMap((s) => s.x), ys = series.flatMap((s) => s.y);
  const xmin = Math.min(...xs), xmax = Math.max(...xs);
  let ymin, ymax;
  if (ylim) {
    [ymin, ymax] = ylim;
  } else {
    ymin = Math.min(...ys, ...refY.map((r) => r.v));
    ymax = Math.max(...ys, ...refY.map((r) => r.v));
    const ypad = (ymax - ymin || 1) * 0.06; ymin -= ypad; ymax += ypad;
  }
  const X = (x) => pad.l + (x - xmin) / (xmax - xmin || 1) * (w - pad.l - pad.r);
  const Y = (y) => h - pad.b - (y - ymin) / (ymax - ymin || 1) * (h - pad.t - pad.b);

  for (let i = 0; i <= 3; i++) {
    const yv = ymin + (i / 3) * (ymax - ymin);
    el("line", { x1: pad.l, y1: Y(yv), x2: w - pad.r, y2: Y(yv), stroke: css("--grid"), "stroke-width": 1 }, svg);
    const t = el("text", { x: pad.l - 6, y: Y(yv) + 3, "text-anchor": "end", class: "axis-label" }, svg);
    t.textContent = yfmt(yv);
  }
  el("line", { x1: pad.l, y1: h - pad.b, x2: w - pad.r, y2: h - pad.b, stroke: css("--baseline"), "stroke-width": 1 }, svg);
  for (let i = 0; i <= 4; i++) {
    const xv = xmin + (i / 4) * (xmax - xmin);
    const t = el("text", { x: X(xv), y: h - pad.b + 14, "text-anchor": "middle", class: "axis-label" }, svg);
    t.textContent = xfmt(xv);
  }
  if (xlabel) { const t = el("text", { x: (pad.l + w - pad.r) / 2, y: h - 2, "text-anchor": "middle", class: "axis-label" }, svg); t.textContent = xlabel; }
  if (ylabel) { const t = el("text", { x: 2, y: 10, class: "axis-label" }, svg); t.textContent = ylabel; }

  for (const r of refX) {
    el("line", { x1: X(r.v), y1: pad.t, x2: X(r.v), y2: h - pad.b, stroke: r.color || css("--copper"),
      "stroke-width": 1, "stroke-dasharray": "4 3" }, svg);
    const t = el("text", { x: X(r.v) + 4, y: pad.t + 9, class: "axis-label", fill: r.color || css("--copper") }, svg);
    t.textContent = r.label;
  }
  for (const r of refY) {
    el("line", { x1: pad.l, y1: Y(r.v), x2: w - pad.r, y2: Y(r.v), stroke: r.color || css("--muted"),
      "stroke-width": 1, "stroke-dasharray": "4 3" }, svg);
    const t = el("text", { x: w - pad.r - 4, y: Y(r.v) - 4, "text-anchor": "end", class: "axis-label" }, svg);
    t.textContent = r.label;
  }

  const clipId = `clip${++_clipSeq}`;
  const clip = el("clipPath", { id: clipId }, el("defs", {}, svg));
  el("rect", { x: pad.l, y: pad.t, width: w - pad.l - pad.r, height: h - pad.t - pad.b }, clip);
  const seriesPaths = [];
  for (const s of series) {
    const d = s.x.map((x, i) => `${i ? "L" : "M"}${X(x).toFixed(1)},${Y(s.y[i]).toFixed(1)}`).join("");
    seriesPaths.push(el("path", { d, fill: "none", stroke: s.color, "stroke-width": 2,
      "stroke-linejoin": "round", "stroke-linecap": "round", "clip-path": `url(#${clipId})` }, svg));
  }
  drawIn(seriesPaths);
  // direct labels at line ends, nudged apart on collision
  const placed = [];
  for (const s of series.filter((s) => s.label)) {
    let ly = Math.min(Math.max(Y(s.y[s.y.length - 1]), pad.t + 10), h - pad.b - 4);
    while (placed.some((p) => Math.abs(p - ly) < 11)) ly -= 11;
    placed.push(ly);
    const t = el("text", { x: w - pad.r - 2, y: ly - 5, "text-anchor": "end", class: "series-label", fill: s.color }, svg);
    t.textContent = s.label;
    if (!REDUCED) {  // labels arrive after their lines finish drawing
      t.style.opacity = "0";
      t.style.transition = "opacity 0.3s ease 0.65s";
      requestAnimationFrame(() => { t.style.opacity = "1"; });
    }
  }

  const tip = html("div", "chart-tip", wrap);
  const hover = el("rect", { x: pad.l, y: pad.t, width: w - pad.l - pad.r, height: h - pad.t - pad.b,
    fill: "transparent" }, svg);
  const cross = el("line", { x1: 0, y1: pad.t, x2: 0, y2: h - pad.b, stroke: css("--ink"),
    "stroke-width": 1, opacity: 0 }, svg);
  hover.addEventListener("mousemove", (ev) => {
    const box = svg.getBoundingClientRect();
    const px = (ev.clientX - box.left) * (w / box.width);
    const xv = xmin + (px - pad.l) / (w - pad.l - pad.r) * (xmax - xmin);
    cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("opacity", 0.35);
    const lines = series.map((s) => {
      let best = 0;
      for (let i = 1; i < s.x.length; i++) if (Math.abs(s.x[i] - xv) < Math.abs(s.x[best] - xv)) best = i;
      return `${s.label || ylabel || "y"} ${yfmt(s.y[best])}`;
    });
    tip.innerHTML = `<strong>${xfmt(xv)}</strong> ${xlabel}<br>` + lines.join("<br>");
    tip.style.display = "block";
    // clamp so the tooltip never overflows the chart card edges
    tip.style.left = `${Math.min(Math.max((px / w) * 100, 14), 86)}%`;
    tip.style.top = `${(pad.t / h) * 100}%`;
  });
  hover.addEventListener("mouseleave", () => { tip.style.display = "none"; cross.setAttribute("opacity", 0); });
  return wrap;
}

/* ---------- fleet tables ---------- */

function chemChip(chem) {
  const c = html("span", `chem-chip ${chem}`);
  c.textContent = chem;
  return c;
}


/* one source of truth: queues drive the summary cards AND the table groups */
const QUEUES = {
  qual: [
    { key: "call", num: "1", title: "Ready to call", tone: "good",
      sub: "interval clear of the line — these come off the cycler today",
      match: (c) => c.verdict === "pass" || c.verdict === "fail" },
    { key: "keep", num: "2", title: "Keep testing", tone: "warn",
      sub: "interval straddles the line — leave on test",
      match: (c) => c.verdict === "keep-testing" },
    { key: "held", num: "3", title: "Held", tone: "plain",
      sub: "out of envelope — review protocol match",
      match: (c) => c.verdict === "out-of-envelope" },
    { key: "ref", title: "Reference", tone: "muted",
      sub: "training cells — they built the model, no verdicts",
      match: (c) => c.verdict === "train", collapsible: true },
  ],
  diag: [
    { key: "quant", num: "1", title: "Quantitative modes", tone: "good",
      sub: "C/18.5 diagnostics + matched references — full LLI/LAM split",
      match: (c) => !!c.modes },
    { key: "featured", num: "2", title: "Featured curves", tone: "plain",
      sub: "NCA & NMC — staged curves, qualitative hints",
      match: (c) => !c.modes && (c.chemistry === "NCA" || c.chemistry === "NMC") },
    { key: "muted", num: "3", title: "Muted diagnostics", tone: "muted",
      sub: "LFP — the flat plateau limits what curves can say",
      match: (c) => !c.modes && c.chemistry === "LFP" },
  ],
};

function renderQueueCards() {
  const box = document.getElementById("queue-cards");
  box.innerHTML = "";
  const cells = (state.fleet === "qual" ? state.data.qual : state.data.diag).cells;
  for (const q of QUEUES[state.fleet]) {
    const n = cells.filter(q.match).length;
    const card = html("button", `queue-card tone-${q.tone}` + (state.queue === q.key ? " active" : ""), box);
    card.innerHTML = `<span class="qc-num">${n}</span>
      <span class="qc-title">${q.num ? `<span class="group-num">${q.num}</span>` : ""}${q.title}</span>
      <span class="qc-sub">${q.sub}</span>`;
    card.title = state.queue === q.key ? "Click to show all queues" : `Show only: ${q.title}`;
    card.addEventListener("click", () => {
      state.queue = state.queue === q.key ? null : q.key;
      if (state.queue === "ref") state.showRef = true;
      renderQueueCards();
      renderFleet();
    });
  }
}

const SORTS = {
  qual: { id: (c) => c.id, split: (c) => c.split, policy: (c) => c.policy,
        cycle_life: (c) => c.cycle_life ?? 1e9, p_pass: (c) => c.p_pass, verdict: (c) => c.verdict },
  diag: { id: (c) => c.id, chemistry: (c) => c.chemistry, temperature_C: (c) => c.temperature_C,
        discharge_rate_C: (c) => c.discharge_rate_C ?? 0.054, fade_frac: (c) => c.fade_frac,
        v_dispersion: (c) => c.v_dispersion, rho: (c) => c.mode_hint.rho ?? -1 },
};

function applySearchSort(cells, haystack) {
  if (state.search) {
    const q = state.search.toLowerCase();
    cells = cells.filter((c) => haystack(c).toLowerCase().includes(q));
  }
  const acc = SORTS[state.fleet][state.sortKey];
  if (acc) {
    cells = [...cells].sort((a, b) => {
      const va = acc(a), vb = acc(b);
      return (va < vb ? -1 : va > vb ? 1 : 0) * state.sortDir;
    });
  }
  return cells;
}

function wireSorting(thead) {
  thead.querySelectorAll("th[data-sort]").forEach((th) => {
    th.classList.add("sortable");
    if (th.dataset.sort === state.sortKey) th.classList.add(state.sortDir > 0 ? "sorted-asc" : "sorted-desc");
    th.addEventListener("click", () => {
      if (state.sortKey === th.dataset.sort) {
        state.sortDir *= -1;
        if (state.sortDir === 1) state.sortKey = null; // third click clears
      } else { state.sortKey = th.dataset.sort; state.sortDir = -1; }
      renderFleet();
    });
  });
}

function renderFleet() {
  const table = document.getElementById("fleet-table");
  table.innerHTML = "";
  const thead = html("thead", "", table);
  const tbody = html("tbody", "", table);
  let rowIdx = 0;

  const groupHeader = (g, count, colspan) => {
    const tr = html("tr", "group-row", tbody);
    const td = html("td", "", tr);
    td.colSpan = colspan;
    const chev = g.collapsible ? (state.showRef ? "▾ " : "▸ ") : "";
    td.innerHTML = `<span class="group-title">${chev}${g.num ? `<span class="group-num">${g.num}</span>` : ""}${g.title.toUpperCase()}
        <span class="group-count">${count}</span></span>
      <span class="group-sub">${g.sub}</span>`;
    if (g.collapsible) {
      tr.classList.add("collapsible");
      tr.addEventListener("click", () => { state.showRef = !state.showRef; renderFleet(); });
      td.title = state.showRef ? "Click to hide reference cells" : "Click to show reference cells";
    }
  };

  let groups = QUEUES[state.fleet];
  if (state.queue) groups = groups.filter((g) => g.key === state.queue);

  if (state.fleet === "qual") {
    thead.innerHTML = `<tr><th data-sort="id">Cell</th>
      <th data-sort="verdict">Verdict</th>
      <th data-sort="p_pass" title="verdict evidence from the first 100 cycles only — the tick is the calibrated probability, the band its Venn-ABERS interval, the notch the 0.5 decision line">Early call</th>
      <th data-sort="cycle_life" class="num" title="ground truth: cycles until capacity fell to 80% (0.88 Ah). Spec threshold T = 700">Cycle life</th>
      <th title="discharge capacity vs cycle number">Capacity fade</th>
      <th data-sort="split" title="train taught the model; primary/secondary are held-out test cells; OOD cells come from a different lab">Split</th>
      <th data-sort="policy" title="fast-charge protocol, e.g. 4.8C(80%)-4.8C = 4.8C to 80% SOC, then 4.8C">Charge policy</th></tr>`;
    let cells = applySearchSort(state.data.qual.cells, (c) => `${c.id} ${c.policy} ${c.split} ${c.verdict}`);
    for (const g of groups) {
      const members = cells.filter(g.match);
      if (!members.length) continue;
      groupHeader(g, members.length, 7);
      if (g.collapsible && !state.showRef) continue;
      for (const c of members) {
        const tr = html("tr", "", tbody);
        tr.style.setProperty("--i", Math.min(rowIdx++, 24));
        tr.tabIndex = 0;
        tr.dataset.id = c.id;
        const idTd = html("td", "cell-id", tr);
        idTd.textContent = c.id.replace("SNL_18650_", "");
        if (c.split === "transfer") idTd.innerHTML += ` <span class="ood-badge">OOD</span>`;
        html("td", "", tr).appendChild(verdictChip(c.verdict));
        const btd = html("td", "", tr);
        const wrapB = html("span", "bracket", btd);
        wrapB.appendChild(verdictBracket(c));
        const ptxt = html("span", "cell-id", wrapB);
        ptxt.textContent = fmt(c.p_pass, 2);
        html("td", "cell-id num", tr).textContent = c.cycle_life ?? "censored";
        html("td", "", tr).appendChild(sparkline(c.fade));
        html("td", "cond", tr).textContent = c.split;
        html("td", "cond", tr).textContent = c.policy;
        tr.addEventListener("click", () => select(c.id));
        tr.addEventListener("keydown", (e) => { if (e.key === "Enter") select(c.id); });
      }
    }
  } else {
    thead.innerHTML = `<tr><th data-sort="id">Cell</th><th data-sort="chemistry">Chemistry</th>
      <th data-sort="rho" title="which degradation mode dominates. ρ = trajectory stability (Spearman vs cycle number); ≥0.8 is the trust bar. 'quantitative' = earned by diagnostics-grade data + matched references">Dominant mode</th>
      <th data-sort="fade_frac" class="num" title="capacity lost over the recorded test">Fade</th>
      <th title="discharge capacity vs cycle number">Capacity fade</th>
      <th data-sort="temperature_C">Temp</th>
      <th data-sort="discharge_rate_C" title="aging discharge rate; C/18.5 marks diagnostics-grade slow cycles">Dis. rate</th>
      <th data-sort="v_dispersion" class="num" title="voltage window holding the central 80% of charge. Wide (0.5-0.6 V) = featured NCA/NMC curves; narrow (~0.15 V) = LFP's muted diagnostics">V-disp.</th></tr>`;
    let cells = applySearchSort(state.data.diag.cells, (c) => `${c.id} ${c.chemistry}`);
    for (const g of groups) {
      const members = cells.filter(g.match);
      if (!members.length) continue;
      groupHeader(g, members.length, 8);
      for (const c of members) {
        const tr = html("tr", "", tbody);
        tr.style.setProperty("--i", Math.min(rowIdx++, 24));
        tr.tabIndex = 0;
        tr.dataset.id = c.id;
        html("td", "cell-id", tr).textContent = c.id.replace("SNL_18650_", "");
        html("td", "", tr).appendChild(chemChip(c.chemistry));
        const m = html("td", "cond", tr);
        m.innerHTML = c.modes
          ? `<span class="cell-id">LLI ${(c.modes.LLI[c.modes.LLI.length - 1] * 100).toFixed(0)}%</span> <span class="mode-rho">ρ=${c.modes.rho_LLI} · quantitative</span>`
          : c.mode_hint.rho != null
            ? `<span class="cell-id">${c.mode_hint.dominant}</span> <span class="mode-rho">ρ=${c.mode_hint.rho}${c.mode_hint.rho < 0.8 ? " ⚠ unstable" : ""}</span>`
            : "–";
        html("td", "cell-id num", tr).textContent = `${(c.fade_frac * 100).toFixed(1)}%`;
        html("td", "", tr).appendChild(sparkline(c.fade));
        html("td", "cond", tr).textContent = `${c.temperature_C} °C`;
        html("td", "cond", tr).textContent = c.diag_rate ?? `${c.discharge_rate_C}C`;
        html("td", "cell-id num", tr).textContent = `${c.v_dispersion.toFixed(2)} V`;
        tr.addEventListener("click", () => select(c.id));
        tr.addEventListener("keydown", (e) => { if (e.key === "Enter") select(c.id); });
      }
    }
  }
  wireSorting(thead);

  document.getElementById("fleet-caption").textContent = state.fleet === "qual"
    ? "Should each cell qualify (≥ 700 cycles)? Verdicts use only the first 100 cycles — true cycle life is shown so you can score the model yourself. Start with queue ①."
    : "What is degrading inside each cell? Grouped by how much the data allows Hectocycle to say.";

  const shown = tbody.querySelectorAll("tr[data-id]").length;
  if (!shown && !tbody.querySelector(".group-row")) {
    const tr = html("tr", "empty-row", tbody);
    const td = html("td", "", tr);
    td.colSpan = 8;
    td.textContent = state.search
      ? `No cells match “${state.search}”.`
      : "Nothing in this queue.";
  }
  const total = (state.fleet === "qual" ? state.data.qual : state.data.diag).cells.length;
  const counter = document.getElementById("result-count");
  if (counter) counter.textContent = shown === total ? `${total} cells` : `${shown} of ${total} cells`;
}

/* ---------- inspector ---------- */

function section(parent, title) {
  const s = html("div", "insp-section", parent);
  html("h3", "", s).textContent = title;
  return s;
}

function kvList(parent, entries) {
  const dl = html("dl", "kv", parent);
  for (const [k, v] of entries) {
    html("dt", "", dl).textContent = k;
    html("dd", "", dl).textContent = v;
  }
}

function renderEmptyInspector() {
  const insp = document.getElementById("inspector");
  insp.innerHTML = "";
  const box = html("div", "inspector-teach", insp);
  html("h3", "teach-title", box).textContent = "How to read a verdict";

  // annotated bracket anatomy — the signature element, decoded in place
  const anat = html("div", "teach-anatomy", box);
  anat.appendChild(verdictBracket({ p_pass: 0.86, p_lo: 0.62, p_hi: 0.97, verdict: "pass" }, { big: true }));
  const notes = html("div", "teach-notes", box);
  notes.innerHTML = `
    <div><span class="teach-key">│</span> tick = calibrated P(pass) from the first 100 cycles</div>
    <div><span class="teach-key">▬</span> band = Venn-ABERS interval — how sure the model is allowed to be</div>
    <div><span class="teach-key">·5·</span> notch = the decision line</div>`;

  const outcomes = html("div", "teach-outcomes", box);
  for (const [v, txt] of [
    ["pass", "interval clears the line → call it, free the cycler"],
    ["keep-testing", "interval straddles the line → more cycling is the honest answer"],
    ["out-of-envelope", "data outside the training envelope → no verdict offered"],
  ]) {
    const row = html("div", "teach-outcome", outcomes);
    row.appendChild(verdictChip(v));
    html("span", "", row).textContent = txt;
  }

  const hint = html("p", "teach-hint", box);
  hint.innerHTML = `Click any row to open its record · <kbd>↑</kbd><kbd>↓</kbd> move · <kbd>Esc</kbd> closes`;
}

function deselect() {
  state.selected = null;
  location.hash = "";
  document.querySelectorAll(".fleet tbody tr").forEach((tr) => tr.classList.remove("selected"));
  renderEmptyInspector();
}

function select(id) {
  state.selected = id;
  location.hash = `${state.fleet}/${id}`;
  document.querySelectorAll(".fleet tbody tr").forEach((tr) =>
    tr.classList.toggle("selected", tr.dataset.id === id));
  const insp = document.getElementById("inspector");
  insp.innerHTML = "";
  insp.scrollTop = 0;
  const closeBtn = html("button", "insp-close", insp);
  closeBtn.textContent = "✕";
  closeBtn.title = "Close (Esc)";
  closeBtn.addEventListener("click", deselect);
  if (state.fleet === "qual") renderQualInspector(insp, state.data.qual.cells.find((c) => c.id === id));
  else renderDiagInspector(insp, state.data.diag.cells.find((c) => c.id === id));
}

/* arrow keys walk the visible fleet rows; Esc closes the inspector */
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "Escape") {
    const scrim = document.querySelector(".welcome-scrim");
    if (scrim) { localStorage.setItem("hectocycle-welcomed", "1"); scrim.remove(); }
    else deselect();
    return;
  }
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  const rows = [...document.querySelectorAll(".fleet tbody tr[data-id]")];
  if (!rows.length) return;
  e.preventDefault();
  const idx = rows.findIndex((r) => r.dataset.id === state.selected);
  const next = rows[Math.min(Math.max(idx + (e.key === "ArrowDown" ? 1 : -1), 0), rows.length - 1)];
  select(next.dataset.id);
  next.scrollIntoView({ block: "nearest", behavior: REDUCED ? "auto" : "smooth" });
});

function renderQualInspector(insp, c) {
  const head = html("div", "insp-head", insp);
  html("div", "insp-id", head).textContent = c.id.replace("SNL_18650_", "");
  html("div", "insp-sub", head).textContent = c.split === "transfer"
    ? `Sandia/SNL · cross-lab transfer cell (same A123 model) · ${c.policy}`
    : `Severson/MATR · ${c.split} split · charge policy ${c.policy}`;

  // lead with the action, not the evidence
  const act = html("div", `action-banner ${c.verdict}`, insp);
  act.textContent = {
    pass: "Call it — this cell can come off the cycler.",
    fail: "Call it — reject early and reallocate the channel.",
    "keep-testing": "Leave on test — recheck at the next checkup cycle.",
    "out-of-envelope": "No verdict — data is outside the training envelope; check protocol match.",
    train: "Reference cell — it trained the model, so it gets no verdict.",
  }[c.verdict] || "";

  const sV = section(insp, "Early call — cycle 100 evidence");
  sV.appendChild(verdictBracket(c, { big: true }));
  const chipRow = html("div", "", sV);
  chipRow.style.margin = "8px 0";
  chipRow.appendChild(verdictChip(c.verdict));
  kvList(sV, [
    ["Calibrated P(pass ≥ T)", fmt(c.p_pass, 3)],
    ...(c.p_lo != null ? [["Venn-ABERS interval", `[${fmt(c.p_lo, 3)}, ${fmt(c.p_hi, 3)}]`]] : []),
    ["True cycle life", c.cycle_life != null
      ? `${c.cycle_life} (T = ${state.data.qual.threshold})`
      : `censored, ≥ 2337 (T = ${state.data.qual.threshold})`],
    ["Ground truth", c.label ? "pass" : "fail"],
  ]);

  if (c.evidence && c.evidence.length) {
    const sE = section(insp, "Verdict evidence over cutoffs");
    for (const e of c.evidence) {
      const row = html("div", "evi-row", sE);
      html("span", "evi-cyc", row).textContent = `cyc ${e.cutoff}`;
      row.appendChild(verdictBracket(
        { p_pass: e.p, p_lo: e.lo, p_hi: e.hi,
          verdict: { 1: "pass", 0: "fail", "-1": "keep-testing" }[String(e.call)] },
        { w: 210, h: 16 }));
      const lbl = html("span", "evi-call", row);
      lbl.textContent = { 1: "call: pass", 0: "call: fail", "-1": "keep testing" }[String(e.call)];
      lbl.dataset.call = e.call;
    }
    const note = html("p", "", sE);
    note.style.cssText = "font-size:11.5px;color:var(--muted);margin-top:8px;line-height:1.5";
    note.textContent = "Each row refits the model with data truncated at that cycle. Watch the interval settle: the earliest cutoff where it clears the decision line is when this cell became callable.";
  }

  const sF = section(insp, "Capacity fade");
  const fade0 = cleanFade(c.fade);
  sF.appendChild(lineChart({
    series: [{ x: fade0.cycle, y: fade0.qd, color: css("--chem-lfp"), label: "" }],
    xlabel: "cycle", ylabel: "Qd (Ah)",
    refX: [{ v: 100, label: "early-call cutoff" }, { v: state.data.qual.threshold, label: `T=${state.data.qual.threshold}`, color: css("--muted") }],
    refY: [{ v: 0.88, label: "EOL 0.88 Ah" }],
  }));

  const sN = section(insp, "Reading this record");
  const note = html("p", "", sN);
  note.style.cssText = "font-size:12px;color:var(--ink-2);line-height:1.55";
  note.textContent = c.split === "transfer"
    ? "Cross-lab transfer cell: same A123 cell model, cycled at Sandia under a different protocol. The production ΔQ(V)-only features transfer (9/9 correct); the discarded protocol features called every one of these long-lived cells FAIL. Details in the early-call study (docs/)."
    : c.verdict === "keep-testing"
      ? "The interval straddles the 0.5 decision line: the early signal cannot separate this cell from the spec threshold yet. Keep cycling — this is the honest answer, not a model failure."
      : c.verdict === "train"
        ? "Training-split cell: it taught the model; it gets no verdict."
        : (() => {
            const cc = state.data.qual.callable_curve.find((r) => r.cutoff === 100);
            return `The interval clears the decision line, so the verdict is callable at 100 cycles. On the combined test set this rule called ${Math.round(cc.called_frac * 100)}% of cells with ${Math.round(cc.acc_on_called * 100)}% accuracy.`;
          })();
}

function renderDiagInspector(insp, c) {
  const head = html("div", "insp-head", insp);
  html("div", "insp-id", head).textContent = c.id.replace("SNL_18650_", "");
  const sub = html("div", "insp-sub", head);
  sub.append(chemChip(c.chemistry));
  sub.append(c.diag_rate
    ? ` · ${c.temperature_C} °C · ${c.diag_rate} diagnostics · ${c.nominal_Ah} Ah nominal · Oxford BDD-1`
    : ` · ${c.temperature_C} °C · ${c.discharge_rate_C}C discharge · ${c.nominal_Ah} Ah nominal`);

  if (c.chemistry === "LFP") {
    const b = html("div", "banner", insp);
    b.innerHTML = `<strong>MUTED DIAGNOSTICS</strong> — LFP's flat 3.3 V plateau compresses ICA features
      into a ${c.v_dispersion.toFixed(2)} V band (NCA/NMC: ~0.5–0.6 V). Curve shapes below carry little
      state information; mode attribution is not offered for this chemistry.`;
  }

  const sF = section(insp, "Capacity fade");
  const fade1 = cleanFade(c.fade);
  sF.appendChild(lineChart({
    series: [{ x: fade1.cycle, y: fade1.qd, color: css(`--chem-${c.chemistry.toLowerCase()}`), label: "" }],
    xlabel: "cycle", ylabel: "Qd (Ah)",
  }));

  if (c.modes) {
    const sQ = section(insp, "Degradation modes — quantitative (C/18.5 + matched references)");
    const legQ = html("div", "legend", sQ);
    legQ.innerHTML = `<span><span class="swatch" style="background:${css("--chem-nca")}"></span>LLI (ρ=${c.modes.rho_LLI})</span>
      <span><span class="swatch" style="background:${css("--chem-nmc")}"></span>LAM_pe (ρ=${c.modes.rho_LAM_pe})</span>
      <span><span class="swatch" style="background:${css("--chem-lfp")}"></span>LAM_ne</span>
      <span><span class="swatch" style="background:${css("--muted")}"></span>measured fade</span>`;
    const fadeQ = cleanFade(c.fade);
    sQ.appendChild(lineChart({
      series: [
        { x: c.modes.cycle, y: c.modes.LLI.map((v) => v * 100), color: css("--chem-nca"), label: "LLI" },
        { x: c.modes.cycle, y: c.modes.LAM_pe.map((v) => v * 100), color: css("--chem-nmc"), label: "LAM_pe" },
        ...(c.modes.LAM_ne ? [{ x: c.modes.cycle, y: c.modes.LAM_ne.map((v) => v * 100), color: css("--chem-lfp"), label: "LAM_ne" }] : []),
        { x: fadeQ.cycle, y: fadeQ.qd.map((v) => 100 * (1 - v / fadeQ.qd[0])), color: css("--muted"), label: "fade" },
      ],
      xlabel: "cycle", ylabel: "% of BOL", yfmt: (v) => fmt(v, 0),
    }));
    const noteQ = html("p", "", sQ);
    noteQ.style.cssText = "font-size:11.5px;color:var(--muted);margin-top:6px;line-height:1.5";
    noteQ.textContent = "The full three-way split is shown because this cell has diagnostics-grade C/18.5 pseudo-OCV data AND chemistry-matched half-cell references (SLIDE Kokam curves). With generic references the anode term absorbs reference error — the pre-registered stability check went from 1/8 to 8/8 cells on matching (see the mode-identifiability study in docs/). LAM_ne ≈ 0 here is the physically expected answer: these cells age by lithium loss, not anode loss.";
  }


  const ages = ["fresh", "mid", "aged"];
  const ageColors = [css("--age-fresh"), css("--age-mid"), css("--age-old")];
  const sI = section(insp, "ICA evolution — dQ/dV");
  const legI = html("div", "legend", sI);
  c.ica.forEach((d, i) => {
    legI.innerHTML += `<span><span class="swatch" style="background:${ageColors[i]}"></span>${ages[i]} (cyc ${d.cycle})</span>`;
  });
  sI.appendChild(lineChart({
    series: c.ica.map((d, i) => ({ x: d.v, y: d.dqdv, color: ageColors[i], label: `cyc ${d.cycle}` })),
    xlabel: "V", ylabel: "dQ/dV (Ah/V)", xfmt: (v) => fmt(v, 2), yfmt: (v) => fmt(v, 1),
  }));

  const sD = section(insp, "DVA — dV/dQ");
  // end-of-window spikes dominate dV/dQ; clamp the view to the mid-curve band
  const dvAll = c.dva.flatMap((d) => d.dvdq).filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  const p95 = dvAll[Math.floor(dvAll.length * 0.95)];
  sD.appendChild(lineChart({
    series: c.dva.map((d, i) => ({ x: d.q, y: d.dvdq, color: ageColors[i], label: `cyc ${d.cycle}` })),
    xlabel: "Q (Ah)", ylabel: "dV/dQ (V/Ah)", xfmt: (v) => fmt(v, 1), yfmt: (v) => fmt(v, 2),
    ylim: [0, p95 * 1.6],
  }));

  if (!c.modes && c.mode_hint.rho != null && c.chemistry !== "LFP") {
    const sM = section(insp, "Dominant degradation mode — qualitative hint");
    const mh = html("div", "mode-hint", sM);
    mh.innerHTML = `<span class="mode-name">${c.mode_hint.dominant}</span>
      <span class="mode-rho">trajectory stability ρ = ${c.mode_hint.rho}</span>
      ${c.mode_hint.rho < 0.8 ? '<span class="mode-flag">⚠ below the 0.8 sanity bar — treat as a hint, not a number</span>' : ""}`;
    kvList(sM, [["Fit closure (median cap err)", `${(c.mode_hint.closure_med * 100).toFixed(1)}% of nominal`]]);
    const note = html("p", "", sM);
    note.style.cssText = "font-size:11.5px;color:var(--muted);margin-top:6px;line-height:1.5";
    note.textContent = "Quantitative LLI/LAM percentages did not pass the mode-stability bar for this data class and are deliberately not shown.";
  }
}

/* ---------- gates pane ---------- */

function renderGates() {
  const pane = document.getElementById("pane-gates");
  pane.innerHTML = "";
  const grid = html("div", "gates-grid", pane);
  const p0 = state.data.qual, p1 = state.data.diag;

  const card0 = html("div", "gate-card", grid);
  card0.innerHTML = `
    <header><h2>EARLY QUALIFICATION CALL</h2>
      <span class="decision-chip">SHIPS AS DECISION SUPPORT</span></header>
    <table>
      <tr><th>run</th><th>balanced acc</th><th>ECE</th><th>verdict</th></tr>
      <tr><td>pre-registered (official gate)</td><td class="num">${p0.gate.prereg.acc}</td>
          <td class="num">${p0.gate.prereg.ece}</td><td class="check-fail">missed the calibration bar (ECE > 0.10)</td></tr>
      <tr><td>hardened (train-side selection)</td><td class="num">${p0.gate.hardened.acc}</td>
          <td class="num">${p0.gate.hardened.ece}</td><td class="check-pass">meets BUILD bars</td></tr>
      <tr><td><strong>production (ΔQ-only, shipped here)</strong></td><td class="num">${p0.gate.production.acc}</td>
          <td class="num">${p0.gate.production.ece}</td><td class="check-pass">OOD ${p0.gate.production.ood}</td></tr>
    </table>
    <div class="gate-note">Early call ships as decision support: calibrated probability + Venn-ABERS
    interval, an explicit KEEP TESTING verdict when the interval straddles 0.5, and an
    OUT-OF-ENVELOPE refusal when any input feature leaves the training range. The shipped model uses
    protocol-invariant ΔQ(V) features only — the full feature set fails 0/9 across labs (early-call study, docs/).</div>
    <div class="small-multiples" id="sm-qual"></div>`;

  const sm = card0.querySelector("#sm-qual");
  const cc = p0.callable_curve;
  const chart1 = lineChart({
    series: [{ x: cc.map((r) => r.cutoff), y: cc.map((r) => r.called_frac * 100), color: css("--chem-nca"), label: "" }],
    w: 260, h: 150, xlabel: "cutoff cycle", ylabel: "cells callable %", yfmt: (v) => fmt(v, 0),
  });
  const chart2 = lineChart({
    series: [{ x: cc.map((r) => r.cutoff), y: cc.map((r) => r.acc_on_called * 100), color: css("--good"), label: "" }],
    w: 260, h: 150, xlabel: "cutoff cycle", ylabel: "accuracy on called %", yfmt: (v) => fmt(v, 1),
  });
  sm.append(chart1, chart2);

  const card1 = html("div", "gate-card", grid);
  const g = p1.gate;
  card1.innerHTML = `
    <header><h2>DEGRADATION-MODE ENGINE</h2><span class="decision-chip">SHIPS AS CURVE TRACKING</span></header>
    <table>
      <tr><th>check</th><th>result</th><th></th></tr>
      <tr><td>fade closure ≤ 3% nominal</td><td class="num">100% of NCA+NMC</td><td class="check-pass">PASS</td></tr>
      <tr><td>mode sanity ρ ≥ 0.8</td><td class="num">37% (need 70%)</td><td class="check-fail">FAIL</td></tr>
      <tr><td>chemistry contrast ≥ 3×</td><td class="num">3.25×</td><td class="check-pass">PASS</td></tr>
      <tr><td>condition systematics</td><td class="num">2 of 3 Preger trends</td><td class="check-pass">PASS</td></tr>
    </table>
    <div class="gate-note">Diagnostics panel ships as ICA/DVA curve tracking with fade-closure QC.
    Mode attribution appears only as a qualitative dominant-mode hint with its stability score —
    NCA decomposition is unidentifiable from 0.5C curves with generic half-cell references
    (five stabilization variants tried; the boundary is physical, not a bug). Details in the degradation-modes study (docs/).</div>`;
}


/* ---------- the science page: in-depth method explainer ---------- */

function renderScience() {
  const pane = document.getElementById("pane-science");
  if (pane.dataset.rendered) return;
  pane.dataset.rendered = "1";
  pane.innerHTML = `
  <article class="science">
    <p class="sci-eyebrow">How Hectocycle works</p>
    <h2 class="sci-title">Three ideas, each earned the hard way.</h2>
    <p class="sci-lead">Everything on the FLEET tab rests on three pieces of science: a signal that predicts
    cycle life from the first 100 cycles, a probability that is honest about its own uncertainty, and a way to
    read <em>what</em> is degrading from the shape of a voltage curve. This page explains each in depth —
    including where they fail, because knowing that is most of the engineering.</p>

    <section class="sci-section">
      <h3>1 · The signal — ΔQ(V)</h3>
      <p>A battery's discharge curve — voltage falling as charge is drawn — is a fingerprint of its internal
      state. Early degradation barely moves the <em>total</em> capacity, which is why simply extrapolating a
      fade curve from 100 cycles fails: at cycle 100 most cells have lost almost nothing. But degradation
      does something subtler first: it <strong>redistributes where charge is stored along the voltage axis</strong>,
      as lithium is consumed by side reactions and electrode kinetics shift.</p>
      <p>Severson et&nbsp;al. (2019) showed how to expose this. Interpolate each cycle's discharge capacity onto a
      fixed grid of voltages, so curves from different cycles become directly subtractable, then take the
      difference between an early and a later cycle:</p>
      <div class="sci-eq">ΔQ(V) = Q<sub>cycle 100</sub>(V) − Q<sub>cycle 10</sub>(V)</div>
      <p>For a healthy long-lived cell this difference is nearly flat. For a cell that will die young it already
      bulges at cycle 100 — and the <strong>variance</strong> of ΔQ(V) turns out to be strikingly log-linear with
      eventual cycle life. Hectocycle's production model uses three statistics of this curve
      (<span class="mono">log₁₀ var</span>, <span class="mono">log₁₀ |min|</span>,
      <span class="mono">log₁₀ |mean|</span>) and nothing else.</p>
      <div class="sci-callout">
        <strong>Why nothing else?</strong> The first model also used protocol covariates — charge time, internal
        resistance. In-domain they helped. Then we scored the model on the same cell model cycled in a
        <em>different lab</em>: charge time there was ~2 hours instead of 7–11 minutes, ~50σ outside training,
        and the model confidently failed every healthy cell — <strong>0/9 correct</strong>. The ΔQ(V)-only model,
        being a within-cell difference that cancels protocol effects, scored <strong>9/9</strong>. That experiment
        is why the fleet has an OUT-OF-ENVELOPE verdict: any input outside the training range gets a refusal,
        not a guess.
      </div>
    </section>

    <section class="sci-section">
      <h3>2 · Honest probability — calibration and the interval</h3>
      <p>A qualification call feeds cost decisions, so the number attached to it must mean what it says:
      among cells given P(pass) = 0.9, about 90% should actually pass. That property is
      <strong>calibration</strong>, and it does not come free — a well-fit classifier can still be badly
      overconfident. Hectocycle measures it as expected calibration error (ECE) and treats it as a shipping gate,
      not a nice-to-have: the first model was <em>rejected</em> with accuracy 0.92 because its ECE missed the
      bar (0.105&nbsp;&gt;&nbsp;0.10).</p>
      <p>The production pipeline earns calibration twice over. First, an isotonic map — a monotone,
      shape-free curve — is fitted from the classifier's raw scores to observed pass rates, using only
      out-of-fold predictions so the map never grades its own homework. Second, and more unusual, every cell
      also gets a <strong>Venn–ABERS interval</strong>: the calibration is refit twice per cell, once forcing its
      label to <em>fail</em> and once to <em>pass</em>, and the two answers [p₀,&nbsp;p₁] bracket what the
      probability is allowed to be. The width of that band is the model confessing how much it could be
      swayed — a guarantee that holds without distributional assumptions (Vovk &amp; Petej, 2014).</p>
      <div class="sci-eq">verdict = PASS if p₀ &gt; 0.5&nbsp;&nbsp;·&nbsp;&nbsp;FAIL if p₁ &lt; 0.5&nbsp;&nbsp;·&nbsp;&nbsp;otherwise KEEP TESTING</div>
      <p>The abstention is the product's core honesty: on held-out test cells, the rule calls
      <strong>74% of the fleet at cycle 100 with 100% accuracy on the calls</strong>, and the cells it refuses
      to call are precisely the ones whose true lives sit near the 700-cycle spec — where more testing is
      genuinely the right answer.</p>
    </section>

    <section class="sci-section">
      <h3>3 · Reading degradation — ICA, DVA, and the three modes</h3>
      <p>The DIAGNOSTICS fleet asks a different question: not <em>how long</em> a cell will live, but
      <em>what is killing it</em>. The tools are two derivatives of the same slow charge curve.
      <strong>Incremental capacity</strong> (dQ/dV) turns flat plateaus into peaks — each peak a phase
      transition in an electrode as lithium fills successive lattice environments. <strong>Differential
      voltage</strong> (dV/dQ) does the inverse. As a cell ages, these peaks shift, shrink, and separate, and
      the pattern of change is a signature of the mechanism.</p>
      <p>To turn signatures into numbers, Hectocycle fits each diagnostic curve with an electrode-alignment
      model in the tradition of Dahn's group:</p>
      <div class="sci-eq">V(Q) = U<sub>pe</sub>(y₀ − Q/C<sub>pe</sub>) − U<sub>ne</sub>(x₀ + Q/C<sub>ne</sub>) + η</div>
      <p>Here U<sub>pe</sub> and U<sub>ne</sub> are reference potential curves for each electrode, and the fitted
      parameters say how much of each electrode is still active (C<sub>pe</sub>, C<sub>ne</sub>) and how the two are
      offset. Tracking them over life yields the three canonical degradation modes:
      <strong>LLI</strong> — loss of cyclable lithium (consumed by SEI growth);
      <strong>LAM<sub>pe</sub></strong> and <strong>LAM<sub>ne</sub></strong> — loss of active material in the
      positive and negative electrode.</p>
      <p>The catch is <strong>identifiability</strong> — many parameter combinations can fit one smooth curve.
      We mapped exactly where the attribution can be trusted:</p>
      <table class="sci-table">
        <tr><th>Data available</th><th>What is trustworthy</th><th>Evidence</th></tr>
        <tr><td>0.5C aging cycles + generic references</td><td>Curve tracking only — no mode split</td>
            <td>NCA trajectories unstable across 5 fitting strategies</td></tr>
        <tr><td>~C/20 diagnostics + generic references</td><td>LLI and LAM<sub>pe</sub></td>
            <td>ρ ≥ 0.92 on 8/8 Oxford cells; LAM<sub>ne</sub> absorbs reference error</td></tr>
        <tr><td>~C/20 diagnostics + <em>matched</em> half-cell references</td><td>Full three-way split</td>
            <td>Pre-registered stability gate: 1/8 → <strong>8/8</strong>, ρ = 1.00</td></tr>
      </table>
      <p>This ladder is enforced in the interface: LFP cells get a muted-diagnostics banner (their flat
      3.3&nbsp;V plateau compresses all features into a ~0.15&nbsp;V band), SNL cells get a qualitative hint
      with its stability score, and only the Oxford fleet — which has diagnostics-grade data and matched
      references — shows quantitative percentages.</p>
    </section>

    <section class="sci-section">
      <h3>4 · The method — gates before features</h3>
      <p>Every capability above passed a <strong>pre-registered, falsifiable gate</strong> before it was allowed
      into the interface: pass criteria written down first, evaluated once, decisions taken as written. Two of
      the three validation studies initially missed their bars — the early call on calibration, the mode engine on
      stability — and the teardowns of those failures produced the two most valuable results in the project
      (the protocol-transfer discovery and the identifiability ladder). The GATES tab shows every number;
      the full teardown documents live in the repository.</p>
      <div class="sci-stats">
        <div><span class="sci-stat">124 + 70 + 8</span><span class="sci-statlab">cells · Severson / Sandia / Oxford</span></div>
        <div><span class="sci-stat">0.043</span><span class="sci-statlab">production ECE (bar ≤ 0.10)</span></div>
        <div><span class="sci-stat">1/8 → 8/8</span><span class="sci-statlab">mode stability, generic → matched refs</span></div>
      </div>
    </section>

    <section class="sci-section sci-refs">
      <h3>Sources</h3>
      <p>Severson et&nbsp;al., <em>Nature Energy</em> 2019 (early prediction from ΔQ(V)) ·
      Preger et&nbsp;al., <em>J.&nbsp;Electrochem.&nbsp;Soc.</em> 2020 (Sandia degradation study) ·
      Birkl &amp; Howey 2017 (Oxford degradation dataset &amp; OCV modelling) ·
      Vovk &amp; Petej 2014 (Venn–ABERS predictors) ·
      half-cell references from PyBaMM parameter sets and the Battery Intelligence Lab's SLIDE.
      Full teardowns: <a href="https://github.com/arjunsharma6251/hectocycle" target="_blank" rel="noopener">github.com/arjunsharma6251/hectocycle</a>
      (docs/early-call-study.md, docs/degradation-modes-study.md, docs/mode-identifiability-study.md).</p>
    </section>
  </article>`;
}


/* ---------- TRY IT: score your own cell, entirely in the browser ---------- */

/* isotonic regression via pool-adjacent-violators; ties on x averaged first
   (mirrors sklearn). Returns { ux, fitted } — fitted value per unique x. */
function pava(xs, ys) {
  const order = xs.map((_, i) => i).sort((a, b) => xs[a] - xs[b]);
  const xsS = order.map((i) => xs[i]), ysS = order.map((i) => ys[i]);
  const ux = [], uy = [], uw = [];
  for (let i = 0; i < xsS.length; i++) {
    if (ux.length && xsS[i] === ux[ux.length - 1]) {
      const k = ux.length - 1;
      uy[k] = (uy[k] * uw[k] + ysS[i]) / (uw[k] + 1);
      uw[k] += 1;
    } else { ux.push(xsS[i]); uy.push(ysS[i]); uw.push(1); }
  }
  const vals = [], wts = [], cnt = [];
  for (let i = 0; i < uy.length; i++) {
    vals.push(uy[i]); wts.push(uw[i]); cnt.push(1);
    while (vals.length > 1 && vals[vals.length - 2] >= vals[vals.length - 1]) {
      const n = vals.length;
      const v = (vals[n - 2] * wts[n - 2] + vals[n - 1] * wts[n - 1]) / (wts[n - 2] + wts[n - 1]);
      wts[n - 2] += wts[n - 1]; cnt[n - 2] += cnt[n - 1];
      vals.pop(); wts.pop(); cnt.pop();
      vals[vals.length - 1] = v;
    }
  }
  const fitted = [];
  for (let b = 0; b < vals.length; b++) for (let r = 0; r < cnt[b]; r++) fitted.push(vals[b]);
  return { ux, fitted };
}

function linearScore(params, x) {
  let z = params.intercept;
  for (let i = 0; i < x.length; i++) z += ((x[i] - params.mean[i]) / params.scale[i]) * params.coef[i];
  return z;
}

function scoreCell(feats) {
  const m = state.data.qual.model;
  const x = m.features.map((f) => feats[f]);

  // calibrated point probability: linear score -> isotonic interpolation
  const z = linearScore(m.point, x);
  const xs = m.point.iso_x, ys = m.point.iso_y;
  let p;
  if (z <= xs[0]) p = ys[0];
  else if (z >= xs[xs.length - 1]) p = ys[ys.length - 1];
  else {
    let i = 0;
    while (xs[i + 1] < z) i++;
    const t = xs[i + 1] === xs[i] ? 0 : (z - xs[i]) / (xs[i + 1] - xs[i]);
    p = ys[i] + t * (ys[i + 1] - ys[i]);
  }

  // Venn-ABERS interval: per fold, refit isotonic with the cell forced to 0 then 1
  const p0s = [], p1s = [];
  for (const fold of m.cvap) {
    const s0 = linearScore(fold, x);
    for (const label of [0, 1]) {
      const { ux, fitted } = pava([...fold.cal_scores, s0], [...fold.cal_labels, label]);
      let idx = ux.findIndex((v) => v >= s0);
      if (idx === -1) idx = ux.length - 1;
      (label === 0 ? p0s : p1s).push(fitted[idx]);
    }
  }
  const mean = (a) => a.reduce((s, v) => s + v, 0) / a.length;
  const p0 = mean(p0s), p1 = mean(p1s);

  const env = state.data.qual.envelope;
  const violations = m.features.filter((f) => feats[f] < env[f][0] || feats[f] > env[f][1]);
  const verdict = violations.length ? "out-of-envelope" : (p0 > 0.5 ? "pass" : p1 < 0.5 ? "fail" : "keep-testing");
  return { p, p0, p1, verdict, violations, feats };
}

/* CSV -> DeltaQ(V) features. Expects discharge points for cycles ~10 and ~100. */
function featurizeCsv(text) {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 20) throw new Error("That file looks too short — expected discharge time-series rows for cycles 10 and 100.");
  const header = lines[0].toLowerCase().split(",").map((h) => h.trim());
  const col = (names) => header.findIndex((h) => names.some((n) => h === n || h.startsWith(n)));
  const ci = col(["cycle"]);
  const vi = col(["voltage", "v"]);
  const qi = col(["discharge_capacity", "capacity", "q"]);
  if (ci === -1 || vi === -1 || qi === -1)
    throw new Error("Couldn't find the columns. Header must include: cycle, voltage_v, discharge_capacity_ah (see the sample file).");
  const byCycle = new Map();
  for (let i = 1; i < lines.length; i++) {
    const parts = lines[i].split(",");
    const c = Math.round(+parts[ci]), v = +parts[vi], q = +parts[qi];
    if (!Number.isFinite(c) || !Number.isFinite(v) || !Number.isFinite(q)) continue;
    if (!byCycle.has(c)) byCycle.set(c, []);
    byCycle.get(c).push([v, q]);
  }
  const nearest = (target, tol) => {
    let best = null;
    for (const c of byCycle.keys()) if (Math.abs(c - target) <= tol && (best === null || Math.abs(c - target) < Math.abs(best - target))) best = c;
    return best;
  };
  const cE = nearest(10, 3), cL = nearest(100, 5);
  if (cE === null || cL === null)
    throw new Error(`Need discharge data at cycle ~10 and cycle ~100. Found cycles: ${[...byCycle.keys()].sort((a, b) => a - b).slice(0, 12).join(", ")}${byCycle.size > 12 ? "…" : ""}`);
  const seg = (c) => {
    const pts = byCycle.get(c).filter((p) => p[1] >= 0).sort((a, b) => a[0] - b[0]);
    if (pts.length < 20) throw new Error(`Cycle ${c} has only ${pts.length} usable points — need a full discharge branch.`);
    return pts;
  };
  const A = seg(cE), B = seg(cL);
  const vLo = Math.max(A[0][0], B[0][0]) + 0.01;
  const vHi = Math.min(A[A.length - 1][0], B[B.length - 1][0]) - 0.01;
  if (vHi <= vLo) throw new Error("The two cycles' voltage ranges don't overlap — check the voltage column units (volts).");
  const interp = (pts, v) => {
    let i = 0;
    while (i < pts.length - 2 && pts[i + 1][0] < v) i++;
    const [v0, q0] = pts[i], [v1, q1] = pts[i + 1];
    return v1 === v0 ? q0 : q0 + (q1 - q0) * (v - v0) / (v1 - v0);
  };
  const N = 1000, dq = [];
  for (let k = 0; k < N; k++) {
    const v = vLo + (k / (N - 1)) * (vHi - vLo);
    dq.push(interp(B, v) - interp(A, v));
  }
  const meanDq = dq.reduce((s, v) => s + v, 0) / N;
  const varDq = dq.reduce((s, v) => s + (v - meanDq) ** 2, 0) / N;
  const minDq = Math.min(...dq);
  const EPS = 1e-12;
  return {
    feats: {
      log_var_dq: Math.log10(varDq + EPS),
      log_min_dq: Math.log10(Math.abs(minDq) + EPS),
      log_mean_dq: Math.log10(Math.abs(meanDq) + EPS),
    },
    cycles: [cE, cL], nPts: [A.length, B.length],
  };
}

function renderTry() {
  const pane = document.getElementById("pane-try");
  if (pane.dataset.rendered) return;
  pane.dataset.rendered = "1";
  pane.innerHTML = `
  <div class="try-wrap">
    <p class="sci-eyebrow">Try it on your cell</p>
    <h2 class="sci-title">Drop a CSV. Get a verdict. Nothing leaves your browser.</h2>
    <p class="sci-lead">Export the discharge time-series of <strong>cycle 10</strong> and <strong>cycle 100</strong>
    from your cycler, three columns: <span class="mono">cycle, voltage_v, discharge_capacity_ah</span>.
    Hectocycle computes the ΔQ(V) features and scores them with the exact production model — the same
    coefficients, the same calibration, the same envelope guard. All locally.</p>
    <div class="dropzone" id="dropzone" tabindex="0" role="button" aria-label="Upload a cell CSV">
      <span class="dz-icon">⇪</span>
      <span class="dz-main">Drop your CSV here, or click to choose</span>
      <span class="dz-sub"><a href="sample_cell.csv" download id="sample-link">Download a sample file</a> — a real Sandia LFP cell this model has never trained on</span>
    </div>
    <input type="file" id="try-file" accept=".csv,text/csv" hidden>
    <div id="try-result"></div>
  </div>`;

  const dz = pane.querySelector("#dropzone");
  const input = pane.querySelector("#try-file");
  dz.addEventListener("click", (e) => { if (e.target.tagName !== "A") input.click(); });
  dz.addEventListener("keydown", (e) => { if (e.key === "Enter") input.click(); });
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
  dz.addEventListener("drop", (e) => {
    e.preventDefault(); dz.classList.remove("drag");
    if (e.dataTransfer.files[0]) handleTryFile(e.dataTransfer.files[0]);
  });
  input.addEventListener("change", () => { if (input.files[0]) handleTryFile(input.files[0]); });
}

function handleTryFile(file) {
  const out = document.getElementById("try-result");
  const reader = new FileReader();
  reader.onload = () => {
    out.innerHTML = "";
    let parsed;
    try { parsed = featurizeCsv(reader.result); }
    catch (err) {
      const e = html("div", "try-error", out);
      e.textContent = err.message;
      return;
    }
    const r = scoreCell(parsed.feats);
    const card = html("div", "try-result-card", out);
    html("div", "insp-id", card).textContent = file.name;
    html("div", "insp-sub", card).textContent =
      `ΔQ(V) from cycles ${parsed.cycles[0]} → ${parsed.cycles[1]} · ${parsed.nPts[0]} + ${parsed.nPts[1]} points · scored in your browser`;
    const act = html("div", `action-banner ${r.verdict}`, card);
    act.style.margin = "16px 0 0";
    act.textContent = {
      pass: "Call it — this cell can come off the cycler.",
      fail: "Call it — reject early and reallocate the channel.",
      "keep-testing": "Leave on test — the interval straddles the decision line.",
      "out-of-envelope": `No verdict — ${r.violations.join(", ")} outside the training envelope. The model refuses rather than extrapolate.`,
    }[r.verdict];
    const bwrap = html("div", "", card);
    bwrap.style.margin = "18px 0 6px";
    bwrap.appendChild(verdictBracket({ p_pass: r.p, p_lo: r.p0, p_hi: r.p1, verdict: r.verdict }, { big: true }));
    const kv = html("dl", "kv", card);
    const rows = [
      ["Calibrated P(pass ≥ 700 cycles)", fmt(r.p, 3)],
      ["Venn–ABERS interval", `[${fmt(r.p0, 3)}, ${fmt(r.p1, 3)}]`],
      ...state.data.qual.model.features.map((f) => {
        const [lo, hi] = state.data.qual.envelope[f];
        const ok = r.feats[f] >= lo && r.feats[f] <= hi;
        return [f, `${fmt(r.feats[f], 3)} ${ok ? "· in envelope" : "· OUTSIDE envelope"}`];
      }),
    ];
    for (const [k, v] of rows) {
      html("dt", "", kv).textContent = k;
      html("dd", "", kv).textContent = v;
    }
    const note = html("p", "try-note", card);
    note.textContent = "Frame of reference: the model was trained on 1.1 Ah LFP fast-charge cells against a 700-cycle spec. "
      + "For other chemistries or specs, treat this as an out-of-distribution demonstration — the envelope guard exists for exactly that reason.";
  };
  reader.readAsText(file);
}

/* ---------- masthead tally + filters ---------- */

function renderTally() {
  const cc100 = state.data.qual.callable_curve.find((r) => r.cutoff === 100);
  const keep = state.data.qual.cells.filter((c) => c.verdict === "keep-testing").length;
  const tally = document.getElementById("tally");
  tally.innerHTML = `
    <div class="tally-item"><span class="tally-num" id="t1"></span>
      <span class="tally-label">callable @ cyc 100</span></div>
    <div class="tally-item"><span class="tally-num" id="t2"></span>
      <span class="tally-label">accuracy on calls</span></div>
    <div class="tally-item"><span class="tally-num" id="t3"></span>
      <span class="tally-label">cells kept testing</span></div>`;
  countUp(document.getElementById("t1"), Math.round(cc100.called_frac * 100), "%");
  countUp(document.getElementById("t2"), Math.round(cc100.acc_on_called * 100), "%", 1100);
  countUp(document.getElementById("t3"), keep, "", 700);
}

function renderFilters() {
  const box = document.getElementById("filters");
  box.innerHTML = "";
  html("span", "result-count", box).id = "result-count";
  const search = html("input", "search", box);
  search.type = "search";
  search.placeholder = "Filter cells…";
  search.value = state.search;
  search.addEventListener("input", () => { state.search = search.value; renderFleet(); });
}

/* ---------- wiring ---------- */

document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => {
    state.tab = t.dataset.tab;
    document.querySelectorAll(".tab").forEach((x) => {
      x.classList.toggle("active", x === t);
      x.setAttribute("aria-selected", x === t);
    });
    document.getElementById("pane-fleet").classList.toggle("hidden", state.tab !== "fleet");
    document.getElementById("pane-gates").classList.toggle("hidden", state.tab !== "gates");
    document.getElementById("pane-science").classList.toggle("hidden", state.tab !== "science");
    document.getElementById("pane-try").classList.toggle("hidden", state.tab !== "try");
    if (state.tab === "science") renderScience();
    if (state.tab === "try") renderTry();
    document.getElementById("fleet-switch").style.visibility = state.tab === "fleet" ? "visible" : "hidden";
    document.getElementById("filters").style.visibility = state.tab === "fleet" ? "visible" : "hidden";
    document.getElementById("inspector").style.display = state.tab === "fleet" ? "" : "none";
  }));

document.querySelectorAll(".seg").forEach((s) =>
  s.addEventListener("click", () => {
    state.fleet = s.dataset.fleet;
    state.filter = null;
    state.queue = null;
    state.search = "";
    state.sortKey = null;
    document.querySelectorAll(".seg").forEach((x) => x.classList.toggle("active", x === s));
    deselect();
    renderFilters(); renderQueueCards(); renderFleet();
  }));

fetch("cockpit_data.json")
  .then((r) => r.json())
  .then((data) => {
    state.data = data;
    // deep link: #<fleet>/<cellId> restores fleet + selection
    const [hFleet, hId] = location.hash.replace("#", "").split("/");
    if (hFleet === "diag" || hFleet === "qual") {
      state.fleet = hFleet;
      document.querySelectorAll(".seg").forEach((x) =>
        x.classList.toggle("active", x.dataset.fleet === hFleet));
    }
    renderTally();
    renderFilters();
    renderQueueCards();
    renderFleet();
    renderGates();
    if (hId && (state.fleet === "qual" ? data.qual : data.diag).cells.some((c) => c.id === hId)) {
      select(hId);
      document.querySelector(`.fleet tbody tr[data-id="${hId}"]`)?.scrollIntoView({ block: "center" });
    } else {
      renderEmptyInspector();
      if (!localStorage.getItem("hectocycle-welcomed")) showWelcome();
    }
  })
  .catch((e) => {
    document.getElementById("pane-fleet").innerHTML =
      `<div class="inspector-empty"><p>Could not load cockpit_data.json — run scripts/build_bundle.py first. (${e})</p></div>`;
  });
