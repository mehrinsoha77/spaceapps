"""Crew health assessment: one astronaut's log -> stressors, health systems, actions.

The log is what the astronaut gathers themselves (daily check-in, self-tests in the
browser, optional heart-beat intervals from any wearable, cabin CO2 readings) plus
radiation doses from SHELTER. `assess(log, as_of_day=D)` uses only entries up to day D,
so the assessment can be replayed day by day without hindsight, like the storm replay.

Output for each of the challenge's four stressors (space radiation, isolation and
confinement, altered gravity, closed environment) and four health systems (immune,
bone, cardiovascular, behavioral): a status (ok / watch / act), the indicators behind
it, and what to do, with a source for each. Statuses are decision support for the
crew and their flight surgeon, not diagnoses.
"""

import numpy as np

from ..physics.limits import GCR_CRUISE_MSV_PER_DAY
from . import models as m

MAX_CHECKINS = 2000
MAX_EVENTS = 500
MAX_SERIES = 3000

SYMPTOMS = {
    "fever": "Fever",
    "infection": "Signs of infection (sore throat, cough, wound)",
    "rash": "Skin rash or hypersensitivity",
    "cold_sore": "Cold sore (latent virus reactivation)",
    "headache": "Headache",
    "congestion": "Nasal congestion",
    "nausea": "Nausea or vomiting",
    "dizziness": "Dizziness or light-headedness",
}

SOURCES = {
    "ncrp132": "NCRP Report 132 short-term limits; NASA-STD-3001 career limit",
    "cdc_ars": "CDC: acute radiation syndrome requires a whole-body dose above 0.7 Gy",
    "leblanc": "LeBlanc et al. 2000: BMD loss 1.06-1.56 %/month in long-duration flight",
    "nasa_co2": "NASA-STD-3001 Vol. 2 [V2 6004]: 1-hour average ppCO2 <= 3 mmHg",
    "law2014": "Law et al. 2014 (J Occup Environ Med): headache odds ~double per +1 mmHg CO2",
    "ochmo_co2": "NASA OCHMO: 7-day average < 2.5 mmHg keeps headache risk < 1 %",
    "taskforce": "Task Force ESC/NASPE 1996: HRV standards (RMSSD, SDNN)",
    "basner2011": "Basner, Mollicone & Dinges 2011: 3-min PVT-B, lapse >= 355 ms",
    "borbely": "Two-process model of sleep (Daan, Beersma & Borbely 1984)",
    "crucian": "Crucian et al. 2016, 2018: immune dysregulation and symptoms in long-duration flight",
    "spc": "Team choice: |z| >= 2 watch, >= 3 act against the astronaut's own baseline",
}


# --------------------------------------------------------------------------- input

def _num(v, name, lo, hi, allow_none=True):
    if v is None or v == "":
        if allow_none:
            return None
        raise ValueError(f"{name} is required")
    x = float(v)
    if not np.isfinite(x) or not lo <= x <= hi:
        raise ValueError(f"{name} must be between {lo:g} and {hi:g}, got {v!r}")
    return x


def _nums(seq, name, lo, hi, cap=MAX_SERIES):
    if seq is None:
        return []
    if not isinstance(seq, list) or len(seq) > cap:
        raise ValueError(f"{name} must be a list of at most {cap} numbers")
    return [_num(v, name, lo, hi, allow_none=False) for v in seq]


def parse_log(raw):
    """Validate a crew log (JSON object). Raises ValueError with a readable message."""
    if not isinstance(raw, dict):
        raise ValueError("the crew log must be a JSON object")
    p = raw.get("profile") or {}
    if not isinstance(p, dict):
        raise ValueError("profile must be an object")
    profile = {
        "name": str(p.get("name") or "Crew member")[:60],
        "gravity_g": _num(p.get("gravity_g", 0.0), "gravity_g", 0, 1.5) or 0.0,
        "gcr_msv_per_day": _num(p.get("gcr_msv_per_day", GCR_CRUISE_MSV_PER_DAY), "gcr_msv_per_day", 0, 10),
        "prior_career_msv": _num(p.get("prior_career_msv", 0.0), "prior_career_msv", 0, 5000) or 0.0,
        "resistive_prescribed_min": _num(p.get("resistive_prescribed_min", 60.0),
                                         "resistive_prescribed_min", 1, 600),
        "planned_days": _num(p.get("planned_days"), "planned_days", 1, 2000),
    }
    if profile["gcr_msv_per_day"] is None:
        profile["gcr_msv_per_day"] = GCR_CRUISE_MSV_PER_DAY
    events = raw.get("radiation_events") or []
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError(f"radiation_events must be a list of at most {MAX_EVENTS}")
    ev = []
    for e in events:
        if not isinstance(e, dict):
            raise ValueError("each radiation event must be an object")
        ev.append({"day": int(_num(e.get("day"), "event day", 0, 5000, allow_none=False)),
                   "bfo": _num(e.get("bfo", 0), "bfo", 0, 1e5) or 0.0,
                   "eye": _num(e.get("eye", 0), "eye", 0, 1e5) or 0.0,
                   "skin": _num(e.get("skin", 0), "skin", 0, 1e6) or 0.0,
                   "label": str(e.get("label") or "Radiation event")[:80]})
    checkins = raw.get("checkins") or []
    if not isinstance(checkins, list) or len(checkins) > MAX_CHECKINS:
        raise ValueError(f"checkins must be a list of at most {MAX_CHECKINS}")
    cs = []
    for c in checkins:
        if not isinstance(c, dict):
            raise ValueError("each check-in must be an object")
        pv = c.get("pvt")
        if pv is not None:
            if not isinstance(pv, dict):
                raise ValueError("pvt must be an object")
            pv = {"rts": _nums(pv.get("rts"), "pvt rts", 0, 60000, cap=1000),
                  "false_starts": int(_num(pv.get("false_starts", 0), "false_starts", 0, 1000) or 0),
                  "duration_s": _num(pv.get("duration_s", 180), "duration_s", 10, 3600) or 180.0,
                  "protocol": str(pv.get("protocol") or "pvt-b")[:20]}
        sym = c.get("symptoms") or []
        if not isinstance(sym, list):
            raise ValueError("symptoms must be a list")
        cs.append({
            "day": int(_num(c.get("day"), "check-in day", 0, 5000, allow_none=False)),
            "sleep_h": _num(c.get("sleep_h"), "sleep_h", 0, 24),
            "wake_clock_h": _num(c.get("wake_clock_h"), "wake_clock_h", 0, 24),
            "mood": _num(c.get("mood"), "mood", 0, 10),
            "stress": _num(c.get("stress"), "stress", 0, 10),
            "resistive_min": _num(c.get("resistive_min"), "resistive_min", 0, 600),
            "co2_mmhg": _num(c.get("co2_mmhg"), "co2_mmhg", 0, 50),
            "resting_hr": _num(c.get("resting_hr"), "resting_hr", 20, 250),
            "rr_ms": _nums(c.get("rr_ms"), "rr_ms", 0, 5000),
            "pvt": pv,
            "symptoms": [s for s in (str(x) for x in sym[:20]) if s in SYMPTOMS],
        })
    cs.sort(key=lambda c: c["day"])
    return {"profile": profile, "radiation_events": ev, "checkins": cs, "synthetic": bool(raw.get("synthetic"))}


# ---------------------------------------------------------------------- assessment

def _col(cs, key):
    return [c[key] for c in cs if c.get(key) is not None]


def _pvt_series(cs):
    """PVT results in order, comparing like with like: only the most common protocol."""
    tests = [(c["day"], c["pvt"]) for c in cs if c.get("pvt") and c["pvt"]["rts"]]
    if not tests:
        return None, []
    protos = [t[1]["protocol"] for t in tests]
    proto = max(set(protos), key=protos.count) if "pvt-b" not in protos else "pvt-b"
    out = []
    for day, t in tests:
        if t["protocol"] != proto:
            continue
        r = m.pvt(t["rts"], t["false_starts"], t["duration_s"])
        if r:
            out.append((day, r))
    return proto, out


def assess(raw_or_log, as_of_day=None):
    """Assess one astronaut. Uses only data with day <= as_of_day (default: latest check-in)."""
    log = parse_log(raw_or_log)                 # idempotent: a parsed log parses to itself
    prof = log["profile"]
    all_days = [c["day"] for c in log["checkins"]] + [e["day"] for e in log["radiation_events"]]
    today = int(as_of_day) if as_of_day is not None else (max(all_days) if all_days else 0)
    cs = [c for c in log["checkins"] if c["day"] <= today]
    events = [e for e in log["radiation_events"] if e["day"] <= today]
    actions = []

    def act(severity, system, text, source):
        actions.append({"severity": severity, "system": system, "text": text, "source": SOURCES[source]})

    # ---- radiation (stressor) -----------------------------------------------------------
    led = m.radiation_ledger(events, today, prof["gcr_msv_per_day"], prof["prior_career_msv"])
    b = led["organs"]["bfo"]
    if led["ars_possible"]:
        act(m.ACT, "immune", f"A single exposure gave {led['max_event_bfo_msv']:.0f} mSv to blood-forming "
            "organs, above the 0.7 Gy acute radiation syndrome threshold. Contact the flight surgeon now "
            "and take a blood count if the medical kit allows.", "cdc_ars")
    if led["status"] != m.OK:
        act(led["status"], "radiation", f"{led['worst_frac'] * 100:.0f} % of a dose limit used; "
            f"{led['remaining30_bfo_msv']:.0f} mSv of 30-day blood-forming-organ budget left. SHELTER now "
            "uses a lower shelter trigger and EVA limit (see Replay).", "ncrp132")

    # ---- bone (altered gravity) ---------------------------------------------------------
    bone = m.bone(today, _col(cs, "resistive_min"), prof["resistive_prescribed_min"],
                  prof["gravity_g"], prof["planned_days"])
    if bone["status"] != m.OK:
        act(bone["status"], "bone", f"Resistive exercise at {bone['adherence_7d'] * 100:.0f} % of your "
            f"{prof['resistive_prescribed_min']:.0f}-minute prescription over the last 7 check-ins. Without "
            "it, long-duration crews lost 1.1-1.6 % of hip and spine bone per month. Restore the "
            "prescribed resistive sessions.", "leblanc")

    # ---- closed environment: CO2 -----------------------------------------------------------
    recent = [c for c in cs if c["day"] > today - 3]
    head = any("headache" in c["symptoms"] for c in recent)
    env = m.co2(_col(cs, "co2_mmhg"), head)
    if env["status"] == m.ACT:
        act(m.ACT, "cardiovascular", f"Cabin CO2 reached {env['max_mmhg']:.1f} mmHg, above the 3 mmHg "
            "standard. Report it, check CO2 removal, and avoid hard exercise in poorly ventilated areas.",
            "nasa_co2")
    elif env["status"] == m.WATCH and env["mean7_mmhg"] is not None:
        act(m.WATCH, "cardiovascular", f"7-day CO2 average {env['mean7_mmhg']:.1f} mmHg: headache odds "
            f"about x{env['headache_odds_x']:.1f} vs 2.5 mmHg." + (" You reported a headache." if head else ""),
            "law2014")

    # ---- cardiovascular: resting HR and HRV against own baseline --------------------------
    hrv_rows = [(c["day"], m.hrv(c["rr_ms"])) for c in cs if c["rr_ms"]]
    hrv_rows = [(d, h) for d, h in hrv_rows if h]
    hr_series = [c["resting_hr"] if c["resting_hr"] is not None else
                 next((h["hr_bpm"] for d, h in hrv_rows if d == c["day"]), None) for c in cs]
    z_hr = m.baseline_z(hr_series)
    z_rmssd = m.baseline_z([h["rmssd_ms"] for _, h in hrv_rows])
    cv_status = m.worst(m.z_status(z_hr, +1), m.z_status(z_rmssd, -1))
    if cv_status != m.OK:
        bits = []
        if m.z_status(z_hr, +1) != m.OK:
            bits.append(f"resting heart rate {z_hr['latest']:.0f} bpm vs your baseline {z_hr['mean']:.0f}")
        if m.z_status(z_rmssd, -1) != m.OK:
            bits.append(f"HRV (RMSSD) {z_rmssd['latest']:.0f} ms vs your baseline {z_rmssd['mean']:.0f}")
        act(cv_status, "cardiovascular", "Outside your own range: " + "; ".join(bits) + ". Re-measure "
            "rested and seated; check hydration, sleep and CO2; tell the flight surgeon if it persists.", "spc")

    # ---- behavioral: PVT, sleep, mood and stress -------------------------------------------
    proto, pvts = _pvt_series(cs)
    z_lapse = m.baseline_z([r["lapses"] for _, r in pvts], n_base=3, rel_floor=0.0)
    if z_lapse is not None:
        z_lapse["sd"] = max(z_lapse["sd"], 1.0)                 # lapses are counts: SD floor of 1
        z_lapse["z"] = (z_lapse["latest"] - z_lapse["mean"]) / z_lapse["sd"]
    z_speed = m.baseline_z([r["speed"] for _, r in pvts], n_base=3)
    cog = m.worst(m.z_status(z_lapse, +1), m.z_status(z_speed, -1))
    if cog != m.OK:
        act(cog, "behavioral", f"Reaction test: {pvts[-1][1]['lapses']} lapses vs your baseline "
            f"{z_lapse['mean']:.1f}. Avoid starting critical tasks (EVA, docking, robotics) until a re-test "
            "after rest is back in range.", "basner2011")
    sleep = m.sleep_pressure(_col(cs, "sleep_h"), _col(cs, "wake_clock_h"))
    if sleep and sleep["status"] != m.OK:
        act(sleep["status"], "behavioral", f"Sleep pressure index {sleep['index']:.2f} (1.0 = rested; "
            f"{sleep['act_at']:.2f} ~ habitual 6 h nights); 7-day average sleep {sleep['mean_sleep_7d_h']:.1f} h"
            + (f"; wake time shifting by {sleep['wake_spread_h']:.1f} h" if sleep['wake_spread_h'] else "")
            + ". Protect a full sleep period; keep wake time fixed.", "borbely")
    z_mood = m.baseline_z(_col(cs, "mood"))
    z_stress = m.baseline_z(_col(cs, "stress"))
    mood_st = m.worst(m.z_status(z_mood, -1), m.z_status(z_stress, +1))
    if mood_st != m.OK:
        act(mood_st, "behavioral", "Mood or stress self-rating is outside your usual range. Use the "
            "planned private conference with family or the psychological support team; tell a crewmate.",
            "spc")
    behav = m.worst(cog, sleep["status"] if sleep else m.OK, mood_st)

    # ---- immune: symptoms + radiation ------------------------------------------------------
    sym = {s for c in recent for s in c["symptoms"]}
    imm = m.ACT if ({"fever", "infection"} & sym or led["ars_possible"]) else \
        m.WATCH if ({"rash", "cold_sore"} & sym) else m.OK
    if {"fever", "infection"} & sym:
        act(m.ACT, "immune", "Fever or signs of infection in the last 3 days: report to the flight surgeon "
            "and follow the crew medical checklist.", "crucian")
    elif {"rash", "cold_sore"} & sym:
        act(m.WATCH, "immune", "Rash or cold sore: common signs of in-flight immune change and latent virus "
            "reactivation. Keep logging; report if it spreads or lasts more than a few days.", "crucian")
    if sleep and sleep["status"] == m.ACT and imm == m.OK and z_stress and m.z_status(z_stress, +1) != m.OK:
        imm = m.WATCH                                            # short sleep + high stress: immune watch
        act(m.WATCH, "immune", "Short sleep together with high stress: both are linked to immune changes in "
            "flight. Prioritise sleep and watch for infection or cold-sore symptoms.", "crucian")

    cardio = m.worst(cv_status, env["status"] if env["status"] == m.ACT else m.OK)
    systems = {
        "immune": {"status": imm, "indicators": [
            {"name": "Symptoms, last 3 days", "value": ", ".join(SYMPTOMS[s] for s in sorted(sym)) or "none"},
            {"name": "Largest single radiation exposure (BFO)", "value": f"{led['max_event_bfo_msv']:.1f} mSv",
             "note": "acute radiation syndrome threshold 700"}]},
        "bone": {"status": bone["status"], "indicators": [
            {"name": "Resistive exercise, last 7 check-ins",
             "value": "no data" if bone["adherence_7d"] is None else f"{bone['adherence_7d'] * 100:.0f} % of prescription"},
            {"name": "Hip loss if unprotected so far",
             "value": f"{bone['projected_unprotected_pct']['trochanter']:.1f} %", "note": "LeBlanc 2000 rate"}],
            "notes": bone["notes"]},
        "cardiovascular": {"status": cardio, "indicators": [
            {"name": "Resting heart rate", "value": _fmt(z_hr, "bpm")},
            {"name": "HRV, RMSSD", "value": _fmt(z_rmssd, "ms")},
            {"name": "Cabin CO2, 7-day average",
             "value": "no data" if env["mean7_mmhg"] is None else f"{env['mean7_mmhg']:.1f} mmHg"}]},
        "behavioral": {"status": behav, "indicators": [
            {"name": "Reaction test lapses (PVT)",
             "value": f"{pvts[-1][1]['lapses']} (baseline {z_lapse['mean']:.1f})" if z_lapse else
             (f"{pvts[-1][1]['lapses']} (building baseline: {len(pvts)}/4 tests)" if pvts else "no test yet")},
            {"name": "Sleep pressure index", "value": "no data" if not sleep else f"{sleep['index']:.2f}",
             "note": "1.0 = rested"},
            {"name": "Mood / stress", "value": _fmt(z_mood, "/10") + " · " + _fmt(z_stress, "/10")}]},
    }
    stressors = {
        "radiation": {"status": led["status"], "value": f"{b['d30_msv']:.0f} of {b['limit30_msv']:.0f} mSv",
                      "detail": "30-day blood-forming-organ dose (cosmic rays + storms)"},
        "isolation": {"status": m.worst(mood_st, sleep["status"] if sleep else m.OK),
                      "value": f"day {today}", "detail": "mission day; mood, stress and sleep tracked"},
        "gravity": {"status": bone["status"], "value": f"{prof['gravity_g']:g} g",
                    "detail": f"{today} days; resistive exercise adherence"},
        "environment": {"status": env["status"],
                        "value": "no CO2 data" if env["mean7_mmhg"] is None else f"{env['mean7_mmhg']:.1f} mmHg CO2",
                        "detail": "7-day average cabin CO2"},
    }
    actions.sort(key=lambda a: -m._RANK[a["severity"]])
    return {
        "as_of_day": today, "name": prof["name"], "synthetic": log["synthetic"],
        "overall": m.worst(*(s["status"] for s in systems.values()), led["status"]),
        "stressors": stressors, "systems": systems, "actions": actions,
        "radiation": led, "bone": bone, "co2": env, "sleep": sleep,
        "pvt": {"protocol": proto, "latest": pvts[-1][1] if pvts else None, "count": len(pvts)},
        "trends": _trends(cs, pvts, hrv_rows),
        "flight_rules": flight_rule_overrides(led, cog, sleep),
        "day_range": [min(all_days) if all_days else 0, max(all_days) if all_days else 0],
    }


def _fmt(z, unit):
    if z is None:
        return "building baseline"
    return f"{z['latest']:.0f} {unit} (baseline {z['mean']:.0f})"


def _trends(cs, pvts, hrv_rows):
    sleep_idx, s = [], m.S_WAKE_REF
    for c in cs:
        if c["sleep_h"] is not None:
            h = c["sleep_h"]
            s = 1 - (1 - s) * np.exp(-(24.0 - h) / m.TAU_RISE_H)
            s = s * np.exp(-h / m.TAU_DECAY_H)
        sleep_idx.append(float(s / m.S_WAKE_REF) if c["sleep_h"] is not None else None)
    return {
        "days": [c["day"] for c in cs],
        "sleep_index": sleep_idx,
        "co2": [c["co2_mmhg"] for c in cs],
        "resting_hr": [c["resting_hr"] for c in cs],
        "mood": [c["mood"] for c in cs],
        "stress": [c["stress"] for c in cs],
        "resistive_min": [c["resistive_min"] for c in cs],
        "pvt_days": [d for d, _ in pvts], "pvt_lapses": [r["lapses"] for _, r in pvts],
        "pvt_mean_rt": [r["mean_rt_ms"] for _, r in pvts],
        "hrv_days": [d for d, _ in hrv_rows], "rmssd": [h["rmssd_ms"] for _, h in hrv_rows],
    }


# ------------------------------------------------------------- coupling to SHELTER

def flight_rule_overrides(ledger, cognition_status, sleep):
    """How this astronaut's state tightens SHELTER's flight rules (team choices, stated):

    * Radiation budget: the shelter trigger becomes at most 5 % of the remaining 30-day BFO
      budget, and the EVA start limit at most 2 %, so a crew member near a limit shelters earlier.
    * Fitness: if the reaction test or sleep pressure is at "act", no EVA starts until re-tested.
    """
    rem = ledger["remaining30_bfo_msv"]
    out, reasons = {"shelter_trigger_max_msv": max(0.1, 0.05 * rem),
                    "eva_start_bfo_max_msv": max(0.05, 0.02 * rem)}, []
    reasons.append(f"{rem:.0f} mSv of 30-day BFO budget left: shelter trigger <= "
                   f"{out['shelter_trigger_max_msv']:.2f} mSv, EVA start limit <= {out['eva_start_bfo_max_msv']:.2f} mSv")
    hold = cognition_status == m.ACT or (sleep is not None and sleep["status"] == m.ACT)
    out["crew_eva_hold"] = bool(hold)
    if hold:
        reasons.append("crew member not fit to start an EVA (reaction test or sleep pressure at 'act')")
    return {"overrides": out, "reasons": reasons}


def apply_to_policy(policy, rules):
    """Tighten (never loosen) a planner Policy with the crew member's flight-rule overrides."""
    o = rules["overrides"]
    policy.shelter_trigger_msv = min(policy.shelter_trigger_msv, o["shelter_trigger_max_msv"])
    policy.eva_start_bfo_msv = min(policy.eva_start_bfo_msv, o["eva_start_bfo_max_msv"])
    policy.crew_eva_hold = policy.crew_eva_hold or o["crew_eva_hold"]
    return policy
