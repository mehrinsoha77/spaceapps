"use strict";
/* SHELTER front end: no libraries, works fully offline. */

const $ = (s) => document.querySelector(s);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const C = {
  hazard: css("--hazard"), caution: css("--caution"), shield: css("--shield"), cabin: css("--cabin"),
  ink: css("--ink"), muted: css("--muted"), line: css("--line"),
};
const CH_COLORS = { "1": "#C9B4C2", "2": "#BE9BB2", "4": "#B07FA0", "5": "#B07FA0", "10": C.hazard,
  "30": "#6F2A7E", "50": "#4B3A8F", "60": "#4B3A8F", "100": "#2D4F8A", "500": "#1F2F4A" };
const PLACE_COLOR = { cabin: C.cabin, shelter: C.shield, eva: C.hazard };
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

const state = { meta: null, ev: null, res: null, k: 0, live: null, val: null };

/* ------------------------------------------------------------ helpers */
async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok) { const e = new Error(body.error || `HTTP ${r.status}`); e.hint = body.hint; throw e; }
  return body;
}
function banner(kind, text) {
  const b = $("#banner");
  if (!kind) { b.hidden = true; b.className = "banner"; return; }
  b.hidden = false; b.className = `banner ${kind}`; b.textContent = text;
}
const fmt = (v, d = 2) => (v == null || !isFinite(v)) ? "–" :
  (Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("en-US") : (+v).toFixed(d));
function pfu(v) { if (v == null || !isFinite(v)) return "–"; if (v >= 100) return Math.round(v).toLocaleString("en-US"); if (v >= 1) return v.toFixed(1); return v.toFixed(2); }
function sLevel(f) { const t = [[1e5,"S5"],[1e4,"S4"],[1e3,"S3"],[100,"S2"],[10,"S1"]]; for (const [v,s] of t) if (f >= v) return s; return "S0"; }
function utc(iso) { const d = new Date(iso); return `${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()} ${String(d.getUTCHours()).padStart(2,"0")}:${String(d.getUTCMinutes()).padStart(2,"0")} UTC`; }
function esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[c])); }

function dayTicks(times, hours) {
  const ticks = []; const span = hours[hours.length - 1] || 1;
  const step = span > 240 ? 2 : 1;
  let n = 0;
  times.forEach((t, i) => {
    const d = new Date(t);
    if (d.getUTCHours() === 0 && d.getUTCMinutes() === 0) {
      if (n++ % step === 0) ticks.push({ x: hours[i], label: `${d.getUTCDate()} ${MON[d.getUTCMonth()]}` });
    }
  });
  return ticks;
}
function hourTicks(times, hours, every) {
  const ticks = [];
  times.forEach((t, i) => { const d = new Date(t);
    if (d.getUTCMinutes() === 0 && d.getUTCHours() % every === 0) ticks.push({ x: hours[i], label: `${String(d.getUTCHours()).padStart(2,"0")}:00` + (d.getUTCHours() === 0 ? ` ${d.getUTCDate()} ${MON[d.getUTCMonth()]}` : "") }); });
  return ticks;
}

/* ------------------------------------------------------------ chart */
function setupCanvas(cv) {
  const dpr = window.devicePixelRatio || 1;
  if (!cv.dataset.h) cv.dataset.h = cv.getAttribute("height");
  const w = cv.clientWidth, h = +cv.dataset.h;
  cv.style.height = h + "px";
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { g, w, h };
}
function supText(v) {
  if (v >= 1000) { const e = Math.round(Math.log10(v)); return e <= 4 ? Number(v).toLocaleString("en-US") : `1e${e}`; }
  return v >= 1 ? String(v) : String(+v.toPrecision(1));
}
function chart(cv, o) {
  const { g, w, h } = setupCanvas(cv);
  const m = { l: o.ml ?? 56, r: 14, t: o.markers && o.markers.length ? 40 : 10, b: 24 };
  g.clearRect(0, 0, w, h);
  g.font = "12px " + getComputedStyle(document.body).fontFamily;
  const xs = o.x; const xmax = o.xmax ?? xs[xs.length - 1] ?? 1, xmin = o.xmin ?? 0;
  let vals = [];
  o.series.forEach((s) => s.y.forEach((v) => { if (v != null && isFinite(v) && (!o.log || v > 0)) vals.push(v); }));
  (o.hlines || []).forEach((l) => vals.push(l.y));
  let ymin, ymax;
  if (o.log) {
    ymin = o.ymin ?? Math.pow(10, Math.floor(Math.log10(Math.max(Math.min(...vals, 1), 1e-4))));
    ymax = o.ymax ?? Math.pow(10, Math.ceil(Math.log10(Math.max(...vals, ymin * 10))));
    if (ymax / ymin < 100) ymax = ymin * 100;
  } else {
    ymin = o.ymin ?? 0; ymax = o.ymax ?? (Math.max(...vals, 1e-6) * 1.1);
  }
  const X = (x) => m.l + (x - xmin) / (xmax - xmin || 1) * (w - m.l - m.r);
  const Y = o.log ? (y) => h - m.b - (Math.log10(Math.max(y, ymin)) - Math.log10(ymin)) / (Math.log10(ymax) - Math.log10(ymin)) * (h - m.t - m.b)
                  : (y) => h - m.b - (y - ymin) / (ymax - ymin || 1) * (h - m.t - m.b);
  cv._map = { X, xmin, xmax, m, w };
  // grid + y labels
  g.strokeStyle = C.line; g.fillStyle = C.muted; g.lineWidth = 1; g.textAlign = "right"; g.textBaseline = "middle";
  const yt = [];
  if (o.log) { for (let e = Math.round(Math.log10(ymin)); e <= Math.round(Math.log10(ymax)); e++) yt.push(Math.pow(10, e)); }
  else { const step = niceStep((ymax - ymin) / 4); for (let v = Math.ceil(ymin / step) * step; v <= ymax + 1e-9; v += step) yt.push(+v.toPrecision(6)); }
  const every = o.log && yt.length > 7 ? 2 : 1;
  yt.forEach((v, i) => { const y = Y(v); g.beginPath(); g.moveTo(m.l, y + .5); g.lineTo(w - m.r, y + .5); g.stroke();
    if (i % every === 0) g.fillText(o.log ? supText(v) : fmt(v, v < 10 ? 1 : 0), m.l - 6, y); });
  // x ticks
  g.textAlign = "center"; g.textBaseline = "top";
  let lastX = -1e9;
  (o.xticks || []).forEach((t) => { const x = X(t.x); g.strokeStyle = C.line; g.beginPath(); g.moveTo(x + .5, h - m.b); g.lineTo(x + .5, h - m.b + 4); g.stroke();
    const tw = g.measureText(t.label).width; if (x - tw / 2 > lastX + 8) { g.fillText(t.label, x, h - m.b + 6); lastX = x + tw / 2; } });
  // threshold lines
  (o.hlines || []).forEach((l) => { if (l.y < ymin || l.y > ymax) return; const y = Y(l.y);
    g.save(); g.strokeStyle = l.color; g.setLineDash([5, 4]); g.lineWidth = 1.5; g.beginPath(); g.moveTo(m.l, y); g.lineTo(w - m.r, y); g.stroke(); g.restore();
    g.fillStyle = l.textColor || C.ink; g.textAlign = "left"; g.textBaseline = "bottom"; g.fillText(l.label, m.l + 4, y - 2); });
  // markers
  const rowEnd = [-1e9, -1e9, -1e9];
  (o.markers || []).forEach((mk) => { if (mk.x < xmin || mk.x > xmax) return; const x = X(mk.x);
    g.save(); g.strokeStyle = mk.color; g.globalAlpha = .7; g.setLineDash([2, 3]); g.beginPath(); g.moveTo(x + .5, m.t); g.lineTo(x + .5, h - m.b); g.stroke(); g.restore();
    const tw = g.measureText(mk.label).width, tx = Math.min(x + 3, w - m.r - tw);
    const r = rowEnd.findIndex((end) => tx > end + 6); if (r < 0) return;
    g.fillStyle = mk.color; g.textAlign = "left"; g.textBaseline = "top"; g.fillText(mk.label, tx, 1 + r * 12); rowEnd[r] = tx + tw; });
  // series
  o.series.forEach((s) => {
    g.save(); g.strokeStyle = s.color; g.lineWidth = s.width || 1.8; if (s.dash) g.setLineDash(s.dash);
    g.beginPath(); let pen = false;
    s.y.forEach((v, i) => { const ok = v != null && isFinite(v) && (!o.log || v > 0);
      if (!ok) { pen = false; return; } const px = X(xs[i]), py = Y(v); pen ? g.lineTo(px, py) : g.moveTo(px, py); pen = true; });
    g.stroke(); g.restore();
  });
  // axis label
  if (o.yLabel) { g.save(); g.fillStyle = C.muted; g.translate(12, (h - m.b + m.t) / 2); g.rotate(-Math.PI / 2); g.textAlign = "center"; g.textBaseline = "top"; g.fillText(o.yLabel, 0, -8); g.restore(); }
  // cursor
  if (o.cursor != null) { const x = X(o.cursor); g.save(); g.strokeStyle = C.ink; g.lineWidth = 1.5; g.beginPath(); g.moveTo(x, m.t); g.lineTo(x, h - m.b); g.stroke(); g.restore(); }
}
function niceStep(raw) { const p = Math.pow(10, Math.floor(Math.log10(raw || 1))); const f = raw / p; return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * p; }
function legend(el, items) { el.innerHTML = items.map((i) => `<span><i style="background:${i.color}${i.dash ? ";background:repeating-linear-gradient(90deg," + i.color + " 0 5px,transparent 5px 8px)" : ""}"></i>${esc(i.label)}</span>`).join(""); }

function strip(cv, places, hours, ref, label) {
  const { g, w, h } = setupCanvas(cv);
  const map = ref._map; if (!map) return;
  g.clearRect(0, 0, w, h);
  g.font = "12.5px " + getComputedStyle(document.body).fontFamily;
  g.fillStyle = C.muted; g.textAlign = "right"; g.textBaseline = "middle";
  g.fillText(label, map.m.l - 8, h / 2);
  for (let i = 0; i < places.length && i < hours.length - 1; i++) {
    g.fillStyle = PLACE_COLOR[places[i]] || C.cabin;
    const x0 = map.X(hours[i]), x1 = map.X(hours[i + 1]);
    g.fillRect(x0, 0, Math.max(x1 - x0 + .4, 1), h);
  }
}

/* ------------------------------------------------------------ tabs */
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", x === b));
  document.querySelectorAll(".tab").forEach((t) => t.hidden = t.id !== `tab-${b.dataset.tab}`);
  const tab = b.dataset.tab;
  if (tab === "replay") { banner(state.ev && state.ev.synthetic ? "synthetic" : null, "SYNTHETIC TEST DATA – not a real storm. Do not present these numbers as results."); redrawReplay(); }
  else banner(null);
  if (tab === "live") loadLive();
  if (tab === "validation") loadValidation();
  if (tab === "method") renderMethod();
}));

/* ------------------------------------------------------------ replay */
const POLICY_FIELDS = [
  ["shelter_trigger_msv", "Shelter when projected cabin BFO dose over the horizon reaches (mSv)", 0.1],
  ["horizon_h", "Look-ahead horizon (h)", 1],
  ["eva_start_bfo_msv", "Hold EVA start if projected EVA BFO dose reaches (mSv)", 0.1],
  ["eva_start_skin_msv", "Hold EVA start if projected EVA skin dose reaches (mSv)", 1],
  ["eva_abort_bfo_msv", "Terminate EVA if projected remaining BFO dose reaches (mSv)", 0.1],
  ["eva_abort_skin_msv", "Terminate EVA if projected remaining skin dose reaches (mSv)", 1],
  ["growth_cap", "Worst-case growth cap (× current rate)", 1],
  ["shelter_exit_rate_msv_h", "Leave shelter when cabin BFO rate is below (mSv/h)", 0.005],
];
function renderPolicy() {
  const d = state.meta.policy_defaults; const box = $("#policy-fields");
  box.innerHTML = POLICY_FIELDS.map(([k, label, step]) =>
    `<label for="pol-${k}">${esc(label)}</label><input id="pol-${k}" type="number" step="${step}" min="0" value="${d[k]}">`).join("") +
    `<label for="pol-s1">Hold EVA start while ≥10 MeV flux is at S1+ and rising</label><input id="pol-s1" type="checkbox" ${d.eva_block_if_s1_rising ? "checked" : ""}>`;
}
function readPolicy() {
  const p = {}; POLICY_FIELDS.forEach(([k]) => { const v = parseFloat($(`#pol-${k}`).value); if (isFinite(v)) p[k] = v; });
  p.eva_block_if_s1_rising = $("#pol-s1").checked; return p;
}
function schedRow(a) {
  const tr = document.createElement("tr");
  tr.innerHTML = `<td><input value="${esc(a.id)}" aria-label="Activity name"></td>
    <td><select aria-label="Type"><option ${a.kind === "EVA" ? "selected" : ""}>EVA</option><option ${a.kind === "BURN" ? "selected" : ""}>BURN</option></select></td>
    <td><input type="number" step="1" min="0" value="${a.start_h}" aria-label="Start hour"></td>
    <td><input type="number" step="0.5" min="0.5" value="${a.duration_h}" aria-label="Length in hours"></td>
    <td><input type="number" step="1" min="0" value="${a.max_delay_h}" aria-label="Maximum delay in hours"></td>
    <td><button class="del" title="Remove" aria-label="Remove activity">✕</button></td>`;
  tr.querySelector(".del").onclick = () => tr.remove();
  $("#sched-body").appendChild(tr);
}
function readSchedule() {
  return [...$("#sched-body").querySelectorAll("tr")].map((tr) => { const f = tr.querySelectorAll("input,select");
    return { id: f[0].value || "ACT", kind: f[1].value, start_h: +f[2].value, duration_h: +f[3].value, max_delay_h: +f[4].value, ingress_min: 30 }; });
}
function resetSchedule() { $("#sched-body").innerHTML = ""; (state.ev?.default_schedule || []).forEach(schedRow); }
$("#add-eva").onclick = () => schedRow({ id: `EVA-${$("#sched-body").children.length + 1}`, kind: "EVA", start_h: 24, duration_h: 6, max_delay_h: 48 });
$("#add-burn").onclick = () => schedRow({ id: `BURN-${$("#sched-body").children.length + 1}`, kind: "BURN", start_h: 30, duration_h: 1, max_delay_h: 0 });
$("#reset-sched").onclick = resetSchedule;

async function loadEvent(id) {
  state.res = null; $("#results").hidden = true; $("#strips").hidden = true; $("#scrub").disabled = true;
  const ev = state.meta.events.find((e) => e.id === id);
  $("#event-why").textContent = ev ? ev.why : "";
  try {
    banner(null);
    state.ev = await api(`/api/event?id=${encodeURIComponent(id)}`);
  } catch (e) {
    state.ev = null;
    banner("error", `${e.message}${e.hint ? " — " + e.hint : ""}`);
    ["#c-flux", "#c-rate"].forEach((s) => { const { g, w, h } = setupCanvas($(s)); g.clearRect(0, 0, w, h); });
    return;
  }
  if (state.ev.synthetic) banner("synthetic", "SYNTHETIC TEST DATA – not a real storm. Do not present these numbers as results.");
  else if (state.ev.notes?.length) banner("stale", state.ev.notes.join(" "));
  $("#scrub").max = state.ev.times.length - 1; state.k = 0; $("#scrub").value = 0;
  resetSchedule(); redrawReplay();
}

function markerX(mk) {
  const t0 = new Date(state.ev.times[0]).getTime();
  return (new Date(mk.time + "Z").getTime() - t0) / 3.6e6;
}
function redrawReplay() {
  const ev = state.ev; if (!ev) return;
  const hrs = ev.hours, cursor = state.res ? hrs[state.k] : null;
  const ticks = dayTicks(ev.times, hrs);
  const chans = Object.keys(ev.channels).filter((c) => ["10", "30", "60", "100"].includes(c));
  const markers = (ev.markers || []).filter((m) => m.kind !== "cme" || /km/.test(m.label))
    .map((m) => ({ x: markerX(m), label: m.label, color: m.kind === "sep" ? C.hazard : m.kind === "flare" ? "#8A6A00" : C.muted }));
  chart($("#c-flux"), { x: hrs, log: true, series: chans.map((c) => ({ y: ev.channels[c], color: CH_COLORS[c], label: `≥${c} MeV` })),
    hlines: [{ y: 10, color: C.caution, label: "S1 radiation storm (10 pfu at ≥10 MeV)" }], markers, xticks: ticks, cursor, yLabel: "pfu", ml: 112 });
  legend($("#legend-flux"), chans.map((c) => ({ color: CH_COLORS[c], label: `≥${c} MeV` })));
  const places = [["eva", "EVA suit"], ["cabin", "Cabin"], ["shelter", "Storm shelter"]];
  chart($("#c-rate"), { x: hrs, log: true, ymin: 1e-4, series: places.map(([p, l]) => ({ y: ev.rates[p].bfo, color: PLACE_COLOR[p], label: l })),
    xticks: ticks, cursor, yLabel: "mSv/h", ml: 112 });
  legend($("#legend-rate"), places.map(([p, l]) => ({ color: PLACE_COLOR[p], label: l })));
  if (state.res) drawResults();
}

$("#run").onclick = async () => {
  if (!state.ev) return;
  const btn = $("#run"); btn.disabled = true; btn.textContent = "Running…";
  try {
    state.res = await api("/api/replay", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_id: state.ev.id, schedule: readSchedule(), policy: readPolicy() }) });
    $("#results").hidden = false; $("#strips").hidden = false; $("#scrub").disabled = false;
    const firstAct = state.res.first_action;
    state.k = firstAct ? Math.max(0, state.ev.hours.findIndex((h) => h >= firstAct.t_h)) : 0;
    $("#scrub").value = state.k;
    redrawReplay(); renderOutcome(); renderLog();
  } catch (e) { banner("error", e.message); }
  finally { btn.disabled = false; btn.textContent = "Run replay"; }
};
$("#scrub").addEventListener("input", (e) => { state.k = +e.target.value; redrawReplay(); highlightLog(); });

function drawResults() {
  const ev = state.ev, r = state.res, hrs = ev.hours;
  strip($("#c-strip-base"), r.place_baseline, hrs, $("#c-flux"), "Follow schedule");
  strip($("#c-strip-pol"), r.place_policy, hrs, $("#c-flux"), "With SHELTER");
  const b = r.bounds.hard;
  chart($("#c-cum"), { x: hrs, series: [
      { y: b.cum_baseline.bfo, color: C.hazard, label: "Follow schedule" },
      { y: b.cum_policy.bfo, color: C.shield, label: "With SHELTER" }],
    xticks: dayTicks(ev.times, hrs), cursor: hrs[state.k], yLabel: "mSv", ml: 72 });
  legend($("#legend-cum"), [{ color: C.hazard, label: "Follow schedule" }, { color: C.shield, label: "With SHELTER" }]);
  renderMoment();
}

function renderMoment() {
  const ev = state.ev, r = state.res, k = state.k, h = ev.hours[k];
  const raw10 = ev.channels["10"][k];
  let k3 = k; while (k3 > 0 && ev.hours[k3] > h - 3) k3--;
  const a = ev.sep10[k3], bnow = ev.sep10[k];
  const trend = a > 0 && bnow > 0 ? bnow / a : null;
  const last = [...r.log].reverse().find((e) => e.t_h <= h + 1e-6);
  const cumB = r.bounds.hard.cum_baseline.bfo[k], cumP = r.bounds.hard.cum_policy.bfo[k];
  const lvl = raw10 != null ? sLevel(raw10) : "–";
  const place = { cabin: "Cabin", shelter: "Storm shelter", eva: "EVA" };
  $("#moment").innerHTML = `
    <div><div class="clock">${utc(ev.times[k])}</div><div class="sub">T+${h.toFixed(0)} h into the replay</div></div>
    <div class="knew">SHELTER sees data up to this hour only.<br>
      ≥10 MeV: <b>${pfu(raw10)} pfu</b> <span class="slevel ${lvl !== "S0" ? "hot" : ""}">${lvl}</span>
      ${trend ? `<br>${trend > 1.05 ? "Rising" : trend < 0.95 ? "Falling" : "Steady"}: ×${trend.toFixed(2)} over 3 h` : ""}</div>
    <dl>
      <dt>Crew, schedule</dt><dd>${place[r.place_baseline[k]] || "–"}</dd>
      <dt>Crew, SHELTER</dt><dd>${place[r.place_policy[k]] || "–"}</dd>
      <dt>Storm dose so far</dt><dd>${fmt(cumB)} vs <b>${fmt(cumP)}</b> mSv BFO</dd>
      <dt>Latest decision</dt><dd>${last ? `<b>${esc(last.action.replace(/_/g, " ").toLowerCase())}</b> at T+${last.t_h.toFixed(0)} h<br>${esc(last.reason)}` : "None yet"}</dd>
    </dl>`;
}

function renderOutcome() {
  const r = state.res, u = r.bounds.hard, l = r.bounds.soft;
  const pct = u.baseline.bfo > 0 ? 100 * u.saved.bfo / u.baseline.bfo : 0;
  const evas = r.evas;
  const delayed = evas.reduce((s, e) => s + e.delay_h, 0);
  const cancelled = evas.filter((e) => e.policy_outcome === "cancelled").length;
  const terminated = evas.filter((e) => e.policy_outcome === "terminated").length;
  const maxv = Math.max(u.baseline.bfo, u.policy.bfo, 1e-9), maxs = Math.max(u.baseline.skin, u.policy.skin, 1e-9);
  $("#outcome").innerHTML = `
    <div class="out-card"><h3>Blood-forming-organ dose avoided (storm only)</h3>
      <div class="big saved">${fmt(u.saved.bfo)} mSv</div>
      <div class="cmp">${pct.toFixed(0)}% less. With a softer high-energy spectrum: ${fmt(l.saved.bfo)} mSv.</div>
      <div class="bar"><b style="width:${100 * u.baseline.bfo / maxv}%"></b></div>
      <div class="bar pol"><b style="width:${100 * u.policy.bfo / maxv}%"></b></div>
      <div class="cmp">Schedule ${fmt(u.baseline.bfo)} mSv · SHELTER ${fmt(u.policy.bfo)} mSv</div></div>
    <div class="out-card"><h3>Skin dose (drives EVA risk)</h3>
      <div class="big">${fmt(u.policy.skin, 1)} mSv</div>
      <div class="cmp">instead of ${fmt(u.baseline.skin, 1)} mSv</div>
      <div class="bar"><b style="width:${100 * u.baseline.skin / maxs}%"></b></div>
      <div class="bar pol"><b style="width:${100 * u.policy.skin / maxs}%"></b></div></div>
    <div class="out-card"><h3>Cost to the mission</h3>
      <div class="big">${fmt(delayed, 0)} h</div>
      <div class="cmp">of EVA delay · ${cancelled} cancelled · ${terminated} ended early · ${fmt(r.shelter_hours, 0)} h in shelter</div></div>
    <div class="out-card"><h3>Unneeded actions (false alarms)</h3>
      <div class="big">${r.false_alarms.count}</div>
      <div class="cmp">Actions that avoided less than ${r.policy_used.false_alarm_msv} mSv in hindsight. Cosmic-ray background over this window, the same either way: ${fmt(r.gcr_msv, 1)} mSv.</div></div>
    <div class="out-card" style="grid-column:1/-1"><h3>EVAs</h3>
      <table class="plain"><thead><tr><th>EVA</th><th>Planned start</th><th>Following the schedule</th><th>With SHELTER</th><th class="num">Delay h</th></tr></thead>
      <tbody>${evas.map((e) => `<tr><td>${esc(e.id)}</td><td>T+${e.planned_start_h} h</td><td>${esc(e.baseline_outcome)}</td><td>${esc(e.policy_outcome)}</td><td class="num">${fmt(e.delay_h, 0)}</td></tr>`).join("") || `<tr><td colspan="5">No EVAs in the schedule.</td></tr>`}</tbody></table></div>`;
}

function renderLog() {
  const ol = $("#log");
  ol.innerHTML = state.res.log.map((e, n) => `<li data-n="${n}" tabindex="0"><span>T+${e.t_h.toFixed(0)} h</span><span class="act ${e.action}">${esc(e.action.replace(/_/g, " ").toLowerCase())}</span><span class="why">${esc(e.reason)}</span></li>`).join("")
    || `<li><span></span><span></span><span class="why">No actions: conditions stayed within the thresholds.</span></li>`;
  ol.querySelectorAll("li[data-n]").forEach((li) => {
    const go = () => { const e = state.res.log[+li.dataset.n]; state.k = Math.max(0, state.ev.hours.findIndex((h) => h >= e.t_h)); $("#scrub").value = state.k; redrawReplay(); highlightLog(); };
    li.onclick = go; li.onkeydown = (ev) => { if (ev.key === "Enter") go(); };
  });
  highlightLog();
}
function highlightLog() {
  if (!state.res) return; const h = state.ev.hours[state.k];
  let best = -1; state.res.log.forEach((e, n) => { if (e.t_h <= h + 1e-6) best = n; });
  document.querySelectorAll("#log li").forEach((li) => li.classList.toggle("active", +li.dataset.n === best));
}

/* ------------------------------------------------------------ live */
async function loadLive() {
  $("#live-meta").textContent = "Loading the latest GOES proton data from NOAA SWPC.";
  try {
    state.live = await api(`/api/live?eva_h=${encodeURIComponent($("#live-eva").value)}`);
  } catch (e) {
    $("#advice").innerHTML = `<div class="empty">Live data unavailable: ${esc(e.message)}. ${esc(e.hint || "Check the internet connection, or use Replay.")}</div>`;
    $("#live-meta").textContent = ""; return;
  }
  const L = state.live, m = L.data_meta || {};
  if (m.stale) banner("stale", `Showing cached data from ${m.fetched_at || "an earlier download"}: live feed unreachable (${m.error || "offline"}).`);
  else banner(null);
  const nc = L.advice.nowcast;
  $("#live-meta").innerHTML = `Latest sample ${utc(L.latest_utc)} · ${esc(L.source)} · ≥10 MeV ${pfu(nc.j10_raw)} pfu (${nc.s_level})${nc.rising ? ", rising" : ""}.`;
  const cls = { GO: "", STAY: "", OK: "", PREPARE: "warn", "NO-GO": "bad", SHELTER: "bad", TERMINATE: "bad" };
  const title = { EVA: "Start a planned EVA now?", SHELTER: "Crew in the cabin", EVA_IN_PROGRESS: "If an EVA is already under way" };
  $("#advice").innerHTML = L.advice.items.map((it) => `<div class="adv ${cls[it.verdict] || ""}"><h3>${title[it.kind]}</h3><div class="verdict">${it.verdict}</div><p>${esc(it.text)}</p></div>`).join("");
  const hrs = L.hours, chans = ["10", "50", "100"].filter((c) => L.channels[c]);
  const t0 = new Date(L.times[0]).getTime();
  const markers = (L.markers || []).map((mk) => ({ x: (new Date(mk.time + "Z").getTime() - t0) / 3.6e6, label: mk.label, color: mk.kind === "sep" ? C.hazard : mk.kind === "flare" ? "#8A6A00" : C.muted }));
  chart($("#c-live"), { x: hrs, log: true, series: chans.map((c) => ({ y: L.channels[c], color: CH_COLORS[c] })),
    hlines: [{ y: 10, color: C.caution, label: "S1" }], markers, xticks: hourTicks(L.times, hrs, 6), yLabel: "pfu" });
  legend($("#legend-live"), chans.map((c) => ({ color: CH_COLORS[c], label: `≥${c} MeV` })));
  const ms = (L.markers || []).slice(-12).reverse();
  $("#live-markers").innerHTML = `<h2>NASA DONKI events, last 7 days</h2>` + (ms.length ?
    `<table class="plain"><tbody>${ms.map((x) => `<tr><td>${utc(x.time + "Z")}</td><td>${esc(x.label)}</td></tr>`).join("")}</tbody></table>` :
    `<p class="hint">No flares, CMEs or SEP events listed${L.marker_status && Object.values(L.marker_status).some((s) => /unavailable/.test(s)) ? " (DONKI unreachable)" : ""}.</p>`);
}
$("#live-refresh").onclick = loadLive;
$("#live-eva").onchange = loadLive;

/* ------------------------------------------------------------ validation */
async function loadValidation() {
  if (!state.val) {
    try { state.val = await api("/api/validation"); }
    catch (e) { $("#val-table").innerHTML = `<div class="empty">${esc(e.message)}<br>${esc(e.hint || "")}</div>`; return; }
  }
  const v = state.val;
  $("#val-table").innerHTML = `<table class="plain"><thead><tr><th>Storm</th><th class="num">Measured by RAD</th><th class="num">SHELTER range</th><th class="num">Ratio</th><th class="num">Calibrated on the other two</th></tr></thead><tbody>
    ${v.rows.map((r) => { const bad = r.ratio_mid > 2 || r.ratio_mid < 0.5;
      return `<tr><td>${esc(r.title)}</td><td class="num">${fmt(r.measured_msv, 1)} mSv</td><td class="num">${fmt(r.predicted_min_msv, 1)}–${fmt(r.predicted_max_msv, 1)} mSv</td>
      <td class="num ${bad ? "bad-ratio" : ""}">×${fmt(r.ratio_mid, 2)}</td><td class="num">${r.loo_prediction_msv != null ? fmt(r.loo_prediction_msv, 1) + " mSv (×" + fmt(r.loo_ratio, 2) + ")" : "–"}</td></tr>`; }).join("")}
    <tr><td><b>Total</b></td><td class="num"><b>${fmt(v.total_measured_msv, 1)} mSv</b></td><td class="num"><b>${fmt(v.total_predicted_mid_msv, 1)} mSv</b></td><td class="num">×${fmt(v.total_predicted_mid_msv / v.total_measured_msv, 2)}</td><td></td></tr></tbody></table>
    <p class="hint">Typical error factor: ×${fmt(v.typical_factor_error, 2)}. Ratio = mid estimate ÷ measurement.</p>`;
  $("#val-notes").innerHTML = `<h2>How to read this</h2><ul>${v.caveats.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>
    <p class="hint">Method: ${esc(v.method)}</p><p class="hint">Measurements: ${esc(v.source)}</p>`;
  drawValidation();
}
function drawValidation() {
  const v = state.val; if (!v) return; const cv = $("#c-val"); const { g, w, h } = setupCanvas(cv);
  const m = { l: 56, r: 16, t: 14, b: 38 };
  const all = v.rows.flatMap((r) => [r.measured_msv, r.predicted_min_msv, r.predicted_max_msv]).filter((x) => x > 0);
  const lo = Math.pow(10, Math.floor(Math.log10(Math.min(...all, 1)))), hi = Math.pow(10, Math.ceil(Math.log10(Math.max(...all, 10))));
  const P = (val, a, b) => (Math.log10(Math.max(val, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo)) * (b - a) + a;
  const X = (x) => P(x, m.l, w - m.r), Y = (y) => P(y, h - m.b, m.t);
  g.font = "12px " + getComputedStyle(document.body).fontFamily; g.clearRect(0, 0, w, h);
  g.strokeStyle = C.line; g.fillStyle = C.muted;
  const dec = []; for (let t = lo; t <= hi * 1.001; t *= 10) dec.push(+t.toPrecision(1));
  dec.forEach((t) => { g.beginPath(); g.moveTo(X(t), m.t); g.lineTo(X(t), h - m.b); g.moveTo(m.l, Y(t)); g.lineTo(w - m.r, Y(t)); g.stroke();
    g.textAlign = "center"; g.textBaseline = "top"; g.fillText(t, X(t), h - m.b + 4); g.textAlign = "right"; g.textBaseline = "middle"; g.fillText(t, m.l - 6, Y(t)); });
  const line = (f, dash, col) => { g.save(); g.strokeStyle = col; g.setLineDash(dash); g.beginPath(); g.moveTo(X(lo), Y(lo * f)); g.lineTo(X(hi), Y(hi * f)); g.stroke(); g.restore(); };
  line(1, [], C.ink); line(2, [4, 4], C.muted); line(0.5, [4, 4], C.muted);
  g.fillStyle = C.muted; g.textAlign = "center"; g.fillText("Measured inside MSL by RAD (mSv)", (m.l + w - m.r) / 2, h - 16);
  g.save(); g.translate(14, (h - m.b + m.t) / 2); g.rotate(-Math.PI / 2); g.fillText("SHELTER estimate (mSv)", 0, 0); g.restore();
  v.rows.forEach((r) => { const x = X(r.measured_msv);
    g.strokeStyle = C.hazard; g.lineWidth = 3; g.beginPath(); g.moveTo(x, Y(r.predicted_min_msv)); g.lineTo(x, Y(r.predicted_max_msv)); g.stroke();
    g.fillStyle = C.hazard; g.beginPath(); g.arc(x, Y(r.predicted_mid_msv), 5, 0, 7); g.fill();
    g.fillStyle = C.ink; g.textAlign = "left"; g.fillText(r.id, x + 8, Y(r.predicted_mid_msv) - 8); });
  g.fillStyle = C.muted; g.textAlign = "left"; g.fillText("dashed: within a factor of 2", m.l + 6, m.t + 8);
}

/* ------------------------------------------------------------ method */
function renderMethod() {
  const M = state.meta; if (!M) return;
  const loc = Object.entries(M.locations).map(([k, l]) => `<tr><td>${esc(l.name)}</td><td>${l.shielding.map(([t, f]) => `${t} g/cm² × ${Math.round(f * 100)}%`).join(", ")}</td><td>${esc(l.source)}</td></tr>`).join("");
  const lim = M.limits.map((l) => `<tr><td>${esc(l.label)}</td><td class="num">${l.value_msv} mSv</td><td>${esc(l.applies_to)}</td><td>${esc(l.source)}</td></tr>`).join("");
  $("#method").innerHTML = `
  <h2>What SHELTER does</h2>
  <p>It reads proton measurements from GOES, works out the radiation dose a crew member would get in a spacesuit, the cabin or a storm shelter, and recommends when to hold or end an EVA and when to shelter. In Replay it does this hour by hour through a real storm, seeing only past data, then scores the decisions against what actually happened.</p>
  <h2>Data</h2>
  <ul>
    <li><b>Historical proton flux:</b> NASA SPDF OMNI2 hourly merged data, proton flux above 1, 2, 4, 10, 30 and 60 MeV (<code>${esc(M.sources.omni2)}</code>).</li>
    <li><b>Live proton flux:</b> NOAA SWPC real-time GOES integral protons, 5-minute data (<code>${esc(M.sources.swpc)}</code>).</li>
    <li><b>Event markers:</b> NASA DONKI flares, CMEs and SEP events (<code>${esc(M.sources.donki)}</code>), with CCMC's DONKI API as fallback.</li>
    <li><b>Benchmark:</b> ${esc(M.sources.rad)}</li>
  </ul>
  <h2>Physics</h2>
  <ul>
    <li>Proton stopping power from the Bethe formula; matches NIST PSTAR within 1.3% for water from 10 to 200 MeV (unit-tested).</li>
    <li>Integral channels become a spectrum with a piecewise power law. Above the highest channel the last slope either continues ("hard") or steepens by 1 ("soft"). Neither is always the higher dose: a soft spectrum puts the same protons at lower energy, which deposits more behind thin shielding and less behind thick shielding. Results show both.</li>
    <li>Protons are slowed through each shield thickness and then through body tissue (skin 0.007, eye 0.3, blood-forming organs 5 g/cm²). Dose equivalent uses the ICRP-60 quality factor.</li>
    <li>Background is removed causally: the 10th percentile of the previous 7 days, never future data.</li>
    <li>Galactic cosmic rays are added as a constant ${M.gcr.msv_per_day} mSv/day: ${esc(M.gcr.source)}</li>
  </ul>
  <h2>Locations</h2>
  <table class="plain"><thead><tr><th>Place</th><th>Shielding distribution (Al-equivalent)</th><th>Basis</th></tr></thead><tbody>${loc}</tbody></table>
  <h2>Reference limits</h2>
  <table class="plain"><thead><tr><th>Limit</th><th class="num">Value</th><th>Applies to</th><th>Source</th></tr></thead><tbody>${lim}</tbody></table>
  <h2>Decision rules</h2>
  <p>Every hour SHELTER projects the next hours two ways: still rising (current growth rate, capped at ${M.policy_defaults.growth_cap}×) and decaying (e-fold ${M.policy_defaults.decay_h} h). Decisions use the rising case. Thresholds are team-chosen defaults, editable in Replay, not NASA flight rules.</p>
  <h2>What it does not model</h2>
  <ul>
    <li>Secondary neutrons and nuclear fragments created in the shielding.</li>
    <li>Real 3D vehicle geometry beyond a thickness distribution, and the body's own geometry beyond one depth per organ.</li>
    <li>The difference between Earth (where GOES is) and a spacecraft far from Earth: magnetic connection to the Sun differs.</li>
    <li>Forecasting before protons arrive. SHELTER reacts to measured flux; it does not predict flares.</li>
  </ul>
  <h2>Related work</h2>
  <p>NASA already has dose tools for flight controllers: MissionDPT (dose projection with UMASEP forecasts) and ARRT (acute risk from onboard dosimeters), and CCMC's SEP Scoreboard compares forecasts. SHELTER's contribution is narrower: turning dose projections into schedule decisions and publishing an hour-by-hour, no-look-ahead backtest of those decisions, plus a public check against MSL/RAD.</p>`;
}

/* ------------------------------------------------------------ boot */
window.addEventListener("resize", () => { clearTimeout(window._rz); window._rz = setTimeout(() => { redrawReplay(); if (state.val) drawValidation(); }, 120); });
(async function boot() {
  try { state.meta = await api("/api/meta"); }
  catch (e) { banner("error", `Server not reachable: ${e.message}`); return; }
  renderPolicy();
  const sel = $("#event");
  sel.innerHTML = state.meta.events.map((e) => `<option value="${e.id}" ${e.cached ? "" : ""}>${esc(e.title)}${e.cached ? "" : " – not downloaded yet"}</option>`).join("");
  const first = state.meta.events.find((e) => e.cached && !e.synthetic) || state.meta.events.find((e) => e.synthetic);
  sel.value = first.id;
  sel.onchange = () => loadEvent(sel.value);
  if (state.meta.offline) document.title = "SHELTER (offline)";
  loadEvent(first.id);
})();
