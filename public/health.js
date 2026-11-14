"use strict";
/* Crew health tab: daily check-in, in-browser reaction test (PVT-B), pulse tapping,
   and the assessment view. Uses helpers from app.js ($, esc, api, banner, chart, legend, C).
   The crew log lives only in this browser (localStorage); the server stores nothing. */
(function () {
  const KEY = "shelter-crew-log-v1";
  const H = { log: null, meta: null, res: null, day: null, pvt: null, started: false };
  const STATUS = { ok: "OK", watch: "Watch", act: "Act now" };
  const SYS = [["immune", "Immune"], ["bone", "Bone"], ["cardiovascular", "Heart, circulation and air"], ["behavioral", "Behavior and cognition"]];
  const STR = [["radiation", "Space radiation"], ["isolation", "Isolation and confinement"], ["gravity", "Altered gravity"], ["environment", "Closed environment"]];
  const SYN_TEXT = "SYNTHETIC DEMO ASTRONAUT – generated data that shows how the monitor works. Use “Start my own log” for real check-ins.";

  const store = {
    get() { try { const t = localStorage.getItem(KEY); return t ? JSON.parse(t) : null; } catch (e) { return null; } },
    set(v) { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch (e) { /* private mode: keep in memory */ } },
  };
  const visible = () => !$("#tab-health").hidden;
  const hbanner = () => { if (visible()) banner(H.log && H.log.synthetic ? "synthetic" : null, SYN_TEXT); };
  const emptyLog = () => ({ synthetic: false, profile: { name: "My log", gravity_g: 0, gcr_msv_per_day: 1.75,
    prior_career_msv: 0, resistive_prescribed_min: 60, planned_days: 180 }, radiation_events: [], checkins: [] });
  const lastDay = () => {
    const d = H.log.checkins.map((c) => c.day).concat(H.log.radiation_events.map((e) => e.day));
    return d.length ? Math.max(...d) : 0;
  };
  const num = (sel) => { const v = $(sel).value.trim(); return v === "" ? null : Number(v); };

  /* ------------------------------------------------------------ assessment */
  async function assess() {
    if (!H.log) return;
    try {
      H.res = await api("/api/health", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ log: H.log, as_of_day: H.day }) });
    } catch (e) { if (visible()) banner("error", `Health assessment failed: ${e.message}`); return; }
    hbanner();
    render();
  }

  function pill(s) { return `<span class="h-pill st-${s}">${STATUS[s]}</span>`; }

  function render() {
    const r = H.res; if (!r) return;
    $("#h-name").textContent = r.name;
    $("#h-src").textContent = H.log.synthetic ? "Synthetic demo data" : `${H.log.checkins.length} check-ins in this browser`;
    $("#h-day").textContent = r.as_of_day;
    const sc = $("#h-scrub"); sc.min = Math.max(0, r.day_range[0]); sc.max = Math.max(r.day_range[1], 0); sc.value = r.as_of_day;
    $("#h-stressors").innerHTML = STR.map(([k, label]) => { const s = r.stressors[k];
      return `<div class="h-chip st-${s.status}"><p class="h-chip-t">${label}</p><p class="h-chip-v">${esc(s.value)}</p><p class="h-chip-d">${esc(s.detail)} · ${STATUS[s.status]}</p></div>`; }).join("");
    $("#h-systems").innerHTML = SYS.map(([k, label]) => { const s = r.systems[k];
      return `<div class="h-card st-${s.status}"><div class="h-card-head"><h3>${label}</h3>${pill(s.status)}</div>
        <dl>${s.indicators.map((i) => `<dt>${esc(i.name)}</dt><dd>${esc(i.value)}${i.note ? ` <span class="hint">(${esc(i.note)})</span>` : ""}</dd>`).join("")}</dl>
        ${(s.notes || []).map((n) => `<p class="hint">${esc(n)}</p>`).join("")}</div>`; }).join("");
    $("#h-actions").innerHTML = r.actions.length ? r.actions.map((a) =>
      `<li class="st-${a.severity}">${pill(a.severity)}<span class="h-act-sys">${esc(a.system)}</span><span class="h-act-t">${esc(a.text)}<br><span class="hint">Source: ${esc(a.source)}</span></span></li>`).join("")
      : `<li class="st-ok">${pill("ok")}<span class="h-act-t">Nothing to act on for this day. Keep checking in.</span></li>`;
    const fr = r.flight_rules;
    $("#h-rules").innerHTML = `<h2>How this changes SHELTER’s storm rules for you</h2><ul>${fr.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
      <p class="hint">Tick “Apply the crew health state” on the Replay tab to replay a real storm with these rules.</p>`;
    drawTrends();
  }

  function ticks(days) {
    if (!days.length) return [];
    const span = days[days.length - 1] - days[0], step = span > 60 ? 10 : 5, out = [];
    for (let d = Math.ceil(days[0] / step) * step; d <= days[days.length - 1]; d += step) out.push({ x: d, label: `day ${d}` });
    return out;
  }

  function drawTrends() {
    const t = H.res.trends, cur = H.res.as_of_day;
    const plot = (id, x, series, extra) => {
      const cv = $(id);
      if (!x.length) { const { g, w, h } = setupCanvas(cv); g.clearRect(0, 0, w, h); g.fillStyle = C.muted; g.font = "13px sans-serif"; g.fillText("No data yet", 12, 24); return; }
      chart(cv, Object.assign({ x, series, xticks: ticks(x), cursor: cur, xmin: x[0], xmax: Math.max(x[x.length - 1], x[0] + 1), ml: 48 }, extra || {}));
    };
    plot("#hc-c-pvt", t.pvt_days, [{ y: t.pvt_lapses, color: C.hazard }], { ymin: 0 });
    const sl = H.res.sleep;
    plot("#hc-c-sleep", t.days, [{ y: t.sleep_index, color: C.shield }], { ymin: 0.8,
      hlines: sl ? [{ y: sl.watch_at, color: C.caution, label: "watch (~7 h nights)" }, { y: sl.act_at, color: C.hazard, label: "act (~6 h nights)" }] : [] });
    const rm = t.days.map((d) => { const i = t.hrv_days.indexOf(d); return i >= 0 ? t.rmssd[i] : null; });
    plot("#hc-c-heart", t.days, [{ y: t.resting_hr, color: C.hazard }, { y: rm, color: C.shield }], { ymin: 0 });
    legend($("#hc-l-heart"), [{ color: C.hazard, label: "resting HR" }, { color: C.shield, label: "HRV (RMSSD)" }]);
    plot("#hc-c-co2", t.days, [{ y: t.co2, color: C.ink }], { ymin: 0,
      hlines: [{ y: 3.0, color: C.hazard, label: "NASA standard 3 mmHg" }, { y: 2.5, color: C.caution, label: "headache guidance 2.5" }] });
  }

  /* ------------------------------------------------------------ forms */
  function fillProfile() {
    const p = H.log.profile;
    $("#hp-name").value = p.name || ""; $("#hp-g").value = p.gravity_g ?? 0; $("#hp-gcr").value = p.gcr_msv_per_day ?? 1.75;
    $("#hp-career").value = p.prior_career_msv ?? 0; $("#hp-res").value = p.resistive_prescribed_min ?? 60; $("#hp-days").value = p.planned_days ?? "";
    $("#hc-day").value = lastDay() + 1;
  }
  function setLog(log) { H.log = log; H.day = null; store.set(log); fillProfile(); assess(); }

  $("#h-demo").onclick = async () => { try { setLog(await api("/api/health/demo")); } catch (e) { banner("error", e.message); } };
  $("#h-new").onclick = () => {
    if (H.log && !H.log.synthetic && H.log.checkins.length && !confirm("Start a new empty log? Export the current one first if you want to keep it.")) return;
    setLog(emptyLog());
  };
  $("#hp-save").onclick = () => {
    const p = H.log.profile;
    p.name = $("#hp-name").value.trim() || "My log"; p.gravity_g = num("#hp-g") ?? 0; p.gcr_msv_per_day = num("#hp-gcr") ?? 1.75;
    p.prior_career_msv = num("#hp-career") ?? 0; p.resistive_prescribed_min = num("#hp-res") ?? 60; p.planned_days = num("#hp-days");
    store.set(H.log); assess();
  };
  $("#hp-export").onclick = () => {
    const blob = new Blob([JSON.stringify(H.log, null, 1)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "shelter-crew-log.json"; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  $("#hp-import").onchange = (ev) => {
    const f = ev.target.files[0]; if (!f) return;
    f.text().then((t) => setLog(JSON.parse(t))).catch((e) => banner("error", `Could not read that file: ${e.message}`));
  };
  $("#h-scrub").addEventListener("change", (e) => { H.day = +e.target.value; assess(); });

  $("#hc-save").onclick = () => {
    const day = num("#hc-day");
    if (day == null || day < 0) { banner("error", "Enter the mission day for this check-in."); return; }
    const c = { day: Math.round(day), symptoms: [...document.querySelectorAll("#hc-sym input:checked")].map((x) => x.value) };
    [["sleep_h", "#hc-sleep"], ["wake_clock_h", "#hc-wake"], ["mood", "#hc-mood"], ["stress", "#hc-stress"],
     ["resistive_min", "#hc-res"], ["co2_mmhg", "#hc-co2"], ["resting_hr", "#hc-hr"]].forEach(([k, s]) => { const v = num(s); if (v != null && isFinite(v)) c[k] = v; });
    const rr = $("#hc-rr").value.split(/[^0-9.]+/).filter(Boolean).map(Number).filter((x) => isFinite(x));
    if (rr.length) c.rr_ms = rr.slice(0, 3000);
    if (H.pvt) c.pvt = H.pvt;
    H.log.checkins = H.log.checkins.filter((x) => x.day !== c.day).concat([c]).sort((a, b) => a.day - b.day);
    store.set(H.log);
    H.pvt = null; $("#hc-pvt-done").textContent = "";
    ["#hc-sleep", "#hc-wake", "#hc-mood", "#hc-stress", "#hc-res", "#hc-co2", "#hc-hr", "#hc-rr"].forEach((s) => { $(s).value = ""; });
    document.querySelectorAll("#hc-sym input").forEach((x) => { x.checked = false; });
    H.day = null; $("#hc-day").value = c.day + 1;
    assess();
  };

  /* ------------------------------------------------------------ PVT-B */
  function runPVT(seconds, protocol) {
    const ov = $("#pvt"), box = $("#pvt-box"), cnt = $("#pvt-count"), meta = $("#pvt-meta");
    const isi = (H.meta && H.meta.pvt.isi_s) || [2, 5];
    const T = { rts: [], fs: 0, end: 0, onset: null, timer: null, raf: null, done: false };
    ov.hidden = false; box.focus();
    cnt.textContent = "Get ready"; meta.textContent = `${seconds} s test · 0 responses`;
    const schedule = () => {
      T.onset = null; cnt.classList.remove("on");
      if (performance.now() >= T.end) return finish();
      T.timer = setTimeout(() => {
        if (T.done) return;
        T.onset = performance.now(); cnt.classList.add("on");
        const tick = () => {
          if (T.onset == null || T.done) return;
          const ms = performance.now() - T.onset;
          cnt.textContent = String(Math.floor(ms));
          if (ms > 30000) { T.rts.push(30000); return schedule(); }   // no response: counted as a 30 s lapse
          T.raf = requestAnimationFrame(tick);
        };
        tick();
      }, (isi[0] + Math.random() * (isi[1] - isi[0])) * 1000);
    };
    const respond = (e) => {
      if (T.done) return;
      if (e.type === "keydown" && e.code !== "Space") return;
      e.preventDefault();
      const now = performance.now();
      if (T.onset == null) { T.fs += 1; cnt.textContent = "Too early"; return; }
      const rt = now - T.onset; T.rts.push(Math.round(rt * 10) / 10);
      cancelAnimationFrame(T.raf); cnt.textContent = `${Math.round(rt)} ms`;
      meta.textContent = `${seconds} s test · ${T.rts.length} responses · ${Math.max(0, Math.ceil((T.end - now) / 1000))} s left`;
      clearTimeout(T.timer); schedule();
    };
    const finish = (aborted) => {
      if (T.done) return; T.done = true;
      clearTimeout(T.timer); cancelAnimationFrame(T.raf);
      document.removeEventListener("keydown", respond); box.removeEventListener("pointerdown", respond);
      ov.hidden = true; cnt.classList.remove("on");
      if (aborted || !T.rts.length) { $("#hc-pvt-done").textContent = "Reaction test stopped; nothing recorded."; return; }
      H.pvt = { rts: T.rts, false_starts: T.fs, duration_s: seconds, protocol };
      const s = [...T.rts].sort((a, b) => a - b), med = s[Math.floor(s.length / 2)];
      const lapses = T.rts.filter((x) => x >= 355).length;
      $("#hc-pvt-done").textContent = `Reaction test done: ${T.rts.length} responses, median ${Math.round(med)} ms, ${lapses} lapses (≥355 ms), ${T.fs} false starts. Save the check-in to keep it.`
        + (protocol !== "pvt-b" ? " The 60 s version is a demo and is compared only with other 60 s tests." : "");
    };
    $("#pvt-stop").onclick = () => finish(true);
    document.addEventListener("keydown", respond); box.addEventListener("pointerdown", respond);
    setTimeout(() => { T.end = performance.now() + seconds * 1000; schedule(); }, 1500);
  }
  $("#hc-pvt").onclick = () => runPVT(180, "pvt-b");
  $("#hc-pvt-short").onclick = () => runPVT(60, "demo-60s");

  /* ------------------------------------------------------------ pulse tapping */
  $("#hc-tap").onclick = () => {
    const ov = $("#tap"), box = $("#tap-box"), cnt = $("#tap-count");
    const taps = []; let timer = null, done = false;
    ov.hidden = false; box.focus(); cnt.textContent = "Tap with each beat";
    const end = (cancel) => {
      if (done) return; done = true; clearTimeout(timer);
      document.removeEventListener("keydown", tap); box.removeEventListener("pointerdown", tap); ov.hidden = true;
      if (cancel || taps.length < 6) { if (!cancel) banner("error", "Too few taps to measure the pulse: try again."); return; }
      const hr = 60000 * (taps.length - 1) / (taps[taps.length - 1] - taps[0]);
      if (hr >= 20 && hr <= 250) $("#hc-hr").value = Math.round(hr);
    };
    const tap = (e) => {
      if (e.type === "keydown" && e.code !== "Space") return;
      e.preventDefault(); taps.push(performance.now());
      if (taps.length === 1) timer = setTimeout(() => end(false), 15000);
      cnt.textContent = `${taps.length} beats`;
    };
    $("#tap-stop").onclick = () => end(true);
    document.addEventListener("keydown", tap); box.addEventListener("pointerdown", tap);
  };

  /* ------------------------------------------------------------ boot */
  async function start() {
    if (H.started) return; H.started = true;
    try { H.meta = await api("/api/health/meta"); } catch (e) { H.meta = null; }
    const sym = (H.meta && H.meta.symptoms) || {};
    $("#hc-sym").innerHTML = "<legend>Symptoms today</legend>" + Object.entries(sym).map(([k, v]) =>
      `<label class="check"><input type="checkbox" value="${esc(k)}"> ${esc(v)}</label>`).join("");
    let log = store.get();
    if (!log) { try { log = await api("/api/health/demo"); } catch (e) { log = emptyLog(); } }
    setLog(log);
  }
  window.healthTab = () => { if (!H.started) start(); else { hbanner(); if (H.res) drawTrends(); } };
  window.crewForReplay = () => (H.log ? { health: H.log, health_day: H.res ? H.res.as_of_day : null } : {});
  window.addEventListener("resize", () => { if (H.res && visible()) drawTrends(); });
  if (visible()) start();
})();
