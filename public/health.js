"use strict";
/* Crew health tab: today's status, daily check-in, in-browser reaction test (PVT-B),
   heart data imported from a wearable, and history. Uses helpers from app.js ($, esc, api, banner, chart, legend, setupCanvas, C).
   The astronaut's own log lives only in this browser (localStorage); the server stores nothing. */
(function () {
  const KEY_OWN = "shelter-crew-log-v1", KEY_MODE = "shelter-crew-mode-v1";
  const H = { mode: "demo", log: null, demo: null, meta: null, res: null, day: null, pvt: null, started: false };
  const STATUS = { ok: "OK", watch: "Watch", act: "Act now" };
  const SYS = [["behavioral", "Alertness, sleep and mood"], ["cardiovascular", "Heart, circulation and air"],
    ["bone", "Bone: countermeasures"], ["immune", "Immune: warning signs"]];
  const STR = [["radiation", "Space radiation"], ["isolation", "Isolation and confinement"],
    ["gravity", "Altered gravity"], ["environment", "Closed cabin air"]];
  const SYS_NAME = { behavioral: "Alertness", cardiovascular: "Heart and air", bone: "Bone", immune: "Immune", radiation: "Radiation" };

  const ls = {
    get(k) { try { const t = localStorage.getItem(k); return t ? JSON.parse(t) : null; } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode: memory only */ } },
  };
  const visible = () => !$("#tab-health").hidden;
  const emptyLog = () => ({ synthetic: false, profile: { name: "My log", gravity_g: 0, gcr_msv_per_day: 1.75,
    prior_career_msv: 0, resistive_prescribed_min: 60, planned_days: 180 }, radiation_events: [], checkins: [] });
  const lastDay = () => {
    const d = H.log.checkins.map((c) => c.day).concat(H.log.radiation_events.map((e) => e.day));
    return d.length ? Math.max(...d) : 0;
  };
  const num = (sel) => { const v = $(sel).value.trim(); return v === "" ? null : Number(v); };
  const plural = (n, a, b) => `${n} ${n === 1 ? a : b}`;
  const hbanner = () => { if (visible()) banner(H.mode === "demo" ? "synthetic" : null,
    "DEMO ASTRONAUT – synthetic data that shows how the monitor works. Press “Use my own log” to start yours."); };

  /* ------------------------------------------------------------ data */
  function persist() { if (H.mode === "own") ls.set(KEY_OWN, H.log); }
  async function useMode(mode) {
    H.mode = mode; ls.set(KEY_MODE, mode); H.day = null; H.pvt = null;
    if (mode === "demo") {
      if (!H.demo) { try { H.demo = await api("/api/health/demo"); } catch (e) { banner("error", e.message); return; } }
      H.log = JSON.parse(JSON.stringify(H.demo));
    } else {
      H.log = ls.get(KEY_OWN) || emptyLog();
    }
    fillProfile(); hbanner(); assess();
  }
  async function assess() {
    if (!H.log) return;
    try {
      H.res = await api("/api/health", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ log: H.log, as_of_day: H.day }) });
    } catch (e) { if (visible()) banner("error", `Health assessment failed: ${e.message}`); return; }
    render();
  }

  /* ------------------------------------------------------------ view */
  const pill = (s) => `<span class="h-pill st-${s}">${STATUS[s]}</span>`;

  function render() {
    const r = H.res; if (!r) return;
    const own = H.mode === "own", n = H.log.checkins.length, latest = lastDay(), past = r.as_of_day < latest;
    $("#h-mode-label").innerHTML = own
      ? `Showing <b>your log</b> · ${plural(n, "check-in", "check-ins")}, saved in this browser`
      : `Showing the <b>demo astronaut</b> (synthetic 40-day mission)`;
    $("#h-switch").textContent = own ? "View the demo astronaut" : "Use my own log";

    const acts = r.actions.filter((a) => a.severity === "act"), watch = r.actions.filter((a) => a.severity === "watch");
    const hero = $("#h-hero");
    hero.className = `h-hero st-${acts.length ? "act" : watch.length ? "watch" : "ok"}`;
    $("#h-hero-kicker").textContent = own && !n ? `${r.name} · no check-ins yet`
      : `${r.name} · mission day ${r.as_of_day}${past ? " (earlier day)" : ""}`;
    let title, sub;
    if (own && !n) { title = "Start with today’s check-in"; sub = "It takes two minutes. After 5 check-ins SHELTER knows your normal range and can spot changes."; }
    else if (acts.length) { title = `${plural(acts.length, "thing needs", "things need")} action`; sub = acts[0].text; }
    else if (watch.length) { title = `All clear · ${plural(watch.length, "thing", "things")} to watch`; sub = watch[0].text; }
    else { title = "All clear"; sub = "Nothing needs action. Keep checking in daily so changes are caught early."; }
    $("#h-hero-title").textContent = title; $("#h-hero-sub").textContent = sub;
    $("#h-steps").hidden = !(own && n < 5);

    $("#h-actions").innerHTML = r.actions.length ? r.actions.map((a) =>
      `<li class="st-${a.severity}">${pill(a.severity)}<div><p class="h-act-sys">${esc(SYS_NAME[a.system] || a.system)}</p><p class="h-act-t">${esc(a.text)}</p><p class="hint">Source: ${esc(a.source)}</p></div></li>`).join("")
      : `<li class="st-ok">${pill("ok")}<div><p class="h-act-t">Nothing to do for this day.</p></div></li>`;
    $("#h-systems").innerHTML = SYS.map(([k, label]) => { const s = r.systems[k];
      return `<div class="h-card st-${s.status}"><div class="h-card-head"><h3>${label}</h3>${pill(s.status)}</div>
        <dl>${s.indicators.map((i) => `<dt>${esc(i.name)}</dt><dd>${esc(i.value)}</dd>`).join("")}</dl>
        ${(s.notes || []).map((x) => `<p class="hint">${esc(x)}</p>`).join("")}</div>`; }).join("");
    $("#h-stressors").innerHTML = STR.map(([k, label]) => { const s = r.stressors[k];
      return `<div class="h-chip st-${s.status}"><p class="h-chip-t">${label}</p><p class="h-chip-v">${esc(s.value)}</p><p class="h-chip-d">${esc(s.detail)}</p>${pill(s.status)}</div>`; }).join("");
    const fr = r.flight_rules;
    $("#h-rules").innerHTML = `<h2>Your storm rules</h2><p class="hint">Your state adjusts SHELTER’s solar-storm decisions:</p>
      <ul>${fr.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
      <p class="hint">See it on a real storm: Replay a storm → tick “Apply the crew health state”.</p>`;

    $("#h-day").textContent = r.as_of_day;
    const sc = $("#h-scrub"); sc.min = Math.max(0, r.day_range[0]); sc.max = Math.max(latest, 0); sc.value = r.as_of_day;
    $("#h-prev").disabled = r.as_of_day <= +sc.min; $("#h-next").disabled = !past; $("#h-latest").disabled = !past;
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
    legend($("#hc-l-heart"), [{ color: C.hazard, label: "resting HR (bpm)" }, { color: C.shield, label: "HRV, RMSSD (ms)" }]);
    plot("#hc-c-co2", t.days, [{ y: t.co2, color: C.ink }], { ymin: 0,
      hlines: [{ y: 3.0, color: C.hazard, label: "NASA standard 3 mmHg" }, { y: 2.5, color: C.caution, label: "headache guidance 2.5" }] });
  }

  /* ------------------------------------------------------------ history */
  const goDay = (d) => { H.day = d; assess(); };
  $("#h-scrub").addEventListener("change", (e) => goDay(+e.target.value));
  $("#h-prev").onclick = () => goDay(Math.max(+$("#h-scrub").min, H.res.as_of_day - 1));
  $("#h-next").onclick = () => goDay(Math.min(lastDay(), H.res.as_of_day + 1));
  $("#h-latest").onclick = () => goDay(null);

  /* ------------------------------------------------------------ check-in */
  function updatePvtNote() {
    $("#hc-pvt-done").textContent = H.pvt
      ? `Reaction test attached: ${H.pvt.rts.length} responses, median ${Math.round(H.pvt.median)} ms, ${H.pvt.lapses} lapses (≥355 ms)${H.pvt.protocol !== "pvt-b" ? " · 60 s demo test, compared only with other demo tests" : ""}.`
      : "No reaction test attached yet.";
  }
  function openCheckin() {
    if (!$("#hc-day").value) $("#hc-day").value = lastDay() + (H.log.checkins.some((c) => c.day === lastDay()) ? 1 : 0) || 1;
    updatePvtNote();
    $("#h-checkin").showModal();
  }
  $("#h-checkin-btn").onclick = openCheckin;
  $("#hc-save").onclick = () => {
    const day = num("#hc-day");
    if (day == null || day < 0) { $("#hc-day").focus(); return; }
    const c = { day: Math.round(day), symptoms: [...document.querySelectorAll("#hc-sym input:checked")].map((x) => x.value) };
    [["sleep_h", "#hc-sleep"], ["wake_clock_h", "#hc-wake"], ["mood", "#hc-mood"], ["stress", "#hc-stress"],
     ["resistive_min", "#hc-res"], ["co2_mmhg", "#hc-co2"], ["resting_hr", "#hc-hr"]].forEach(([k, s]) => {
      const v = num(s); if (v != null && isFinite(v)) c[k] = v; });
    if (H.rr) c.rr_ms = H.rr.slice(0, 1000);     // a 5-minute HRV recording is ~300-500 beats
    if (H.pvt) c.pvt = { rts: H.pvt.rts, false_starts: H.pvt.false_starts, duration_s: H.pvt.duration_s, protocol: H.pvt.protocol };
    H.log.checkins = H.log.checkins.filter((x) => x.day !== c.day).concat([c]).sort((a, b) => a.day - b.day);
    persist();
    H.pvt = null; H.rr = null; $("#hc-rr-done").textContent = "No heart file attached.";
    $("#hc-form").reset(); $("#hc-day").value = c.day + 1;
    $("#h-checkin").close();
    H.day = null; assess();
    if (H.mode === "demo") banner("synthetic", "Saved to the demo astronaut for this visit only. Press “Use my own log” to keep your own check-ins.");
  };

  /* ------------------------------------------------------------ profile */
  function fillProfile() {
    const p = H.log.profile;
    $("#hp-name").value = p.name || ""; $("#hp-g").value = p.gravity_g ?? 0; $("#hp-gcr").value = p.gcr_msv_per_day ?? 1.75;
    $("#hp-career").value = p.prior_career_msv ?? 0; $("#hp-res").value = p.resistive_prescribed_min ?? 60; $("#hp-days").value = p.planned_days ?? "";
    $("#hc-day").value = "";
  }
  function renderEvents() {
    const ev = H.log.radiation_events;
    $("#hp-events").innerHTML = ev.length ? ev.map((e, i) => `<li><span>Day ${e.day}: ${esc(e.label)} · BFO ${e.bfo} mSv, eye ${e.eye}, skin ${e.skin}</span>
      <button class="ghost" type="button" data-i="${i}">Remove</button></li>`).join("")
      : `<li class="hint">None yet. Add one from Replay a storm → “Add to my log”.</li>`;
    $("#hp-events").querySelectorAll("button[data-i]").forEach((b) => b.onclick = () => {
      H.log.radiation_events = H.log.radiation_events.filter((_, j) => j !== +b.dataset.i);
      persist(); renderEvents(); assess();
    });
  }
  $("#h-profile-btn").onclick = () => { renderEvents(); $("#h-profile").showModal(); };
  $("#h-switch").onclick = () => useMode(H.mode === "own" ? "demo" : "own");
  $("#h-demo").onclick = () => { $("#h-profile").close(); useMode("demo"); };
  $("#h-new").onclick = () => {
    if (ls.get(KEY_OWN) && !confirm("Start a new, empty log? Your current log is replaced: export it first to keep it.")) return;
    ls.set(KEY_OWN, emptyLog()); $("#h-profile").close(); useMode("own");
  };
  $("#hp-save").onclick = () => {
    const p = H.log.profile;
    p.name = $("#hp-name").value.trim() || "My log"; p.gravity_g = num("#hp-g") ?? 0; p.gcr_msv_per_day = num("#hp-gcr") ?? 1.75;
    p.prior_career_msv = num("#hp-career") ?? 0; p.resistive_prescribed_min = num("#hp-res") ?? 60; p.planned_days = num("#hp-days");
    persist(); $("#h-profile").close(); assess();
  };
  $("#hp-export").onclick = () => {
    const blob = new Blob([JSON.stringify(H.log, null, 1)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "shelter-crew-log.json"; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  $("#hp-import").onchange = (ev) => {
    const f = ev.target.files[0]; if (!f) return;
    f.text().then((t) => { const log = JSON.parse(t); log.synthetic = false; ls.set(KEY_OWN, log); $("#h-profile").close(); useMode("own"); })
      .catch((e) => banner("error", `Could not read that file: ${e.message}`));
  };

  /* ------------------------------------------------------------ PVT-B */
  function runPVT(seconds, protocol) {
    if ($("#h-checkin").open) $("#h-checkin").close();
    const ov = $("#pvt"), box = $("#pvt-box"), cnt = $("#pvt-count"), meta = $("#pvt-meta");
    const isi = (H.meta && H.meta.pvt.isi_s) || [2, 5];
    const T = { rts: [], fs: 0, end: 0, onset: null, timer: null, raf: null, done: false };
    ov.hidden = false; box.focus();
    cnt.textContent = "Get ready"; meta.textContent = `${seconds} s test · starts in a moment`;
    const schedule = () => {
      T.onset = null; cnt.classList.remove("on");
      if (performance.now() >= T.end) return finish(false);
      T.timer = setTimeout(() => requestAnimationFrame(() => {
        if (T.done) return;
        // start timing in the frame that first draws the counter, not before it
        cnt.textContent = "0"; cnt.classList.add("on"); T.onset = performance.now();
        const tick = () => {
          if (T.onset == null || T.done) return;
          const ms = performance.now() - T.onset;
          cnt.textContent = String(Math.floor(ms));
          if (ms > 30000) { T.rts.push(30000); return schedule(); }   // no response: counted as a 30 s lapse
          T.raf = requestAnimationFrame(tick);
        };
        T.raf = requestAnimationFrame(tick);
      }), (isi[0] + Math.random() * (isi[1] - isi[0])) * 1000);
    };
    const respond = (e) => {
      if (T.done || !T.end) return;
      if (e.type === "keydown" && (e.code !== "Space" || e.repeat)) return;   // a held key is not a response
      e.preventDefault();
      const now = performance.now();
      if (T.onset == null) { T.fs += 1; cnt.textContent = "Too early"; return; }
      const rt = now - T.onset; T.rts.push(Math.round(rt * 10) / 10);
      cancelAnimationFrame(T.raf); cnt.textContent = `${Math.round(rt)} ms`;
      meta.textContent = `${T.rts.length} responses · ${Math.max(0, Math.ceil((T.end - now) / 1000))} s left`;
      clearTimeout(T.timer); schedule();
    };
    const finish = (aborted) => {
      if (T.done) return; T.done = true;
      clearTimeout(T.timer); cancelAnimationFrame(T.raf);
      document.removeEventListener("keydown", respond); box.removeEventListener("pointerdown", respond);
      ov.hidden = true; cnt.classList.remove("on");
      if (!aborted && T.rts.length) {
        const s = [...T.rts].sort((a, b) => a - b);
        H.pvt = { rts: T.rts, false_starts: T.fs, duration_s: seconds, protocol,
          median: s[Math.floor(s.length / 2)], lapses: T.rts.filter((x) => x >= 355).length };
      }
      openCheckin();                                   // result goes into today's check-in
    };
    $("#pvt-stop").onclick = () => finish(true);
    document.addEventListener("keydown", respond); box.addEventListener("pointerdown", respond);
    setTimeout(() => { if (!T.done) { T.end = performance.now() + seconds * 1000; meta.textContent = `${seconds} s test · running`; schedule(); } }, 1500);
  }
  $("#hc-pvt").onclick = () => runPVT(180, "pvt-b");
  $("#hc-pvt-in").onclick = () => runPVT(180, "pvt-b");
  $("#hc-pvt-short").onclick = () => runPVT(60, "demo-60s");

  /* ------------------------------------------------------------ wearable heart file */
  // An RR-interval export from a chest strap or watch app: a column headed "RR"/"RR-interval"/"IBI"
  // (Polar, Elite HRV and similar exports), or one interval per line. Milliseconds or seconds.
  function parseRR(text) {
    const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    if (!lines.length) return null;
    const cells = (l) => l.split(/[;,\t]|\s{2,}/).map((x) => x.trim());
    const col = cells(lines[0]).map((h) => h.toLowerCase()).findIndex((h) => /(^|[^a-z])(rr|ibi|r-r)([^a-z]|$)/.test(h));
    const vals = [];
    for (const l of (col >= 0 ? lines.slice(1) : lines)) {
      const c = cells(l), v = Number(col >= 0 ? c[col] : c[c.length - 1]);
      if (isFinite(v) && v > 0) vals.push(v);
    }
    if (vals.length < 30) return null;
    const median = vals.slice().sort((a, b) => a - b)[vals.length >> 1];
    const rr = vals.map((v) => (median < 5 ? v * 1000 : v)).filter((v) => v >= 300 && v <= 2000);
    return rr.length >= 30 ? rr : null;
  }
  $("#hc-rr-file").onchange = (ev) => {
    const f = ev.target.files[0]; if (!f) return;
    f.text().then((t) => {
      const rr = parseRR(t);
      ev.target.value = "";
      if (!rr) { H.rr = null; $("#hc-rr-done").textContent = `No beat-to-beat (RR) intervals found in ${f.name}. Export RR intervals, not heart-rate samples.`; return; }
      H.rr = rr;
      const hr = 60000 / (rr.reduce((a, b) => a + b, 0) / rr.length);
      if (!$("#hc-hr").value) $("#hc-hr").value = Math.round(hr);
      $("#hc-rr-done").textContent = `Imported ${rr.length} beats from ${f.name} (${(rr.reduce((x, y) => x + y, 0) / 60000).toFixed(1)} min, average ${Math.round(hr)} bpm). HRV is computed when you save.`;
    }).catch((e) => { $("#hc-rr-done").textContent = `Could not read that file: ${e.message}`; });
  };

  /* ------------------------------------------------------------ boot */
  async function start() {
    if (H.started) return; H.started = true;
    try { H.meta = await api("/api/health/meta"); } catch (e) { H.meta = null; }
    const sym = (H.meta && H.meta.symptoms) || {};
    $("#hc-sym").innerHTML = "<legend>Symptoms today</legend>" + Object.entries(sym).map(([k, v]) =>
      `<label class="check"><input type="checkbox" value="${esc(k)}"> ${esc(v)}</label>`).join("");
    useMode(ls.get(KEY_MODE) === "own" ? "own" : "demo");
  }
  window.healthTab = () => { if (!H.started) start(); else { hbanner(); if (H.res) drawTrends(); } };
  window.crewForReplay = () => (H.log ? { health: H.log, health_day: H.res ? H.res.as_of_day : null } : {});
  window.crewNextDay = () => (H.log ? Math.max(lastDay(), 1) : 1);
  window.addCrewDose = (e) => {                    // a storm dose from the Replay tab
    if (!H.log) return "Open the Crew health tab first.";
    const day = Math.round(Number(e.day));
    if (!(day >= 0 && day <= 5000)) return "Enter the mission day of the storm.";
    const r3 = (x) => Math.round(Math.max(0, Number(x) || 0) * 1000) / 1000;
    H.log.radiation_events = H.log.radiation_events.concat([{ day, bfo: r3(e.bfo), eye: r3(e.eye), skin: r3(e.skin),
      label: String(e.label || "Solar storm").slice(0, 80) }]);
    persist(); renderEvents(); H.day = null; assess();
    return `Added on mission day ${day} to ${H.mode === "own" ? "your log" : "the demo astronaut (this visit only)"}. Open Crew health to see your updated dose budget.`;
  };
  window.addEventListener("resize", () => { if (H.res && visible()) drawTrends(); });
  if (visible()) start();
})();
