"""Crew health indicator models.

Each function turns logged data into indicators an astronaut can read and act on.
Every constant names its source. Thresholds that are team choices say so: they are
not NASA flight rules or medical criteria. Nothing here is a diagnosis.

Where a population norm is not well established, an indicator is compared with the
astronaut's OWN baseline (first check-ins, or values they enter), which is how
NASA's in-flight cognition testing is interpreted as well.
"""

import math

import numpy as np

from ..physics.limits import GCR_CRUISE_MSV_PER_DAY

OK, WATCH, ACT = "ok", "watch", "act"
_RANK = {OK: 0, WATCH: 1, ACT: 2}


def worst(*levels):
    return max(levels, key=lambda s: _RANK[s]) if levels else OK


# --------------------------------------------------------------------- radiation

# NCRP Report 132 short-term limits (Gy-Eq ~ mSv dose equivalent here), as tabulated by NASA.
LIMITS_30D_MSV = {"bfo": 250.0, "eye": 1000.0, "skin": 1500.0}
LIMITS_YEAR_MSV = {"bfo": 500.0, "eye": 2000.0, "skin": 3000.0}
CAREER_LIMIT_MSV = 600.0          # NASA-STD-3001 career effective dose
ARS_THRESHOLD_MSV = 700.0         # CDC: acute radiation syndrome needs > 0.7 Gy whole-body.
#                                   Applied to BFO dose equivalent (>= absorbed dose): conservative.
RAD_WATCH, RAD_ACT = 0.5, 0.8     # fraction of a limit used. Team choice.


def radiation_ledger(events, today, gcr_msv_per_day=GCR_CRUISE_MSV_PER_DAY, prior_career_msv=0.0):
    """Dose used so far against NCRP-132 30-day and annual limits and the career limit.

    events: [{"day": int, "bfo": mSv, "eye": mSv, "skin": mSv, "label": str}] from solar storms
            (e.g. a SHELTER replay result) or any other logged exposure.
    Galactic cosmic rays add `gcr_msv_per_day` to every organ every mission day (MSL/RAD cruise
    value by default; the same value for all organs is an approximation, stated in the UI).
    Career effective dose is approximated by the BFO dose equivalent (stated).
    """
    today = int(today)
    out = {"organs": {}, "events": [], "notes": []}
    for organ in ("bfo", "eye", "skin"):
        d30 = gcr_msv_per_day * min(30, today)
        d365 = gcr_msv_per_day * min(365, today)
        dall = gcr_msv_per_day * today
        for e in events:
            if e["day"] > today:              # a future entry is never counted (causal)
                continue
            v = float(e.get(organ, 0.0))
            dall += v
            if e["day"] > today - 30:
                d30 += v
            if e["day"] > today - 365:
                d365 += v
        f30, f365 = d30 / LIMITS_30D_MSV[organ], d365 / LIMITS_YEAR_MSV[organ]
        out["organs"][organ] = {"d30_msv": d30, "year_msv": d365, "mission_msv": dall,
                                "limit30_msv": LIMITS_30D_MSV[organ], "limit_year_msv": LIMITS_YEAR_MSV[organ],
                                "frac30": f30, "frac_year": f365}
    career = prior_career_msv + out["organs"]["bfo"]["mission_msv"]
    out["career_msv"] = career
    out["career_frac"] = career / CAREER_LIMIT_MSV
    acute = max((float(e.get("bfo", 0.0)) for e in events if e["day"] <= today), default=0.0)
    out["max_event_bfo_msv"] = acute
    out["ars_possible"] = acute > ARS_THRESHOLD_MSV
    frac = max([o["frac30"] for o in out["organs"].values()]
               + [o["frac_year"] for o in out["organs"].values()] + [out["career_frac"]])
    out["worst_frac"] = frac
    out["status"] = ACT if frac >= RAD_ACT or out["ars_possible"] else WATCH if frac >= RAD_WATCH else OK
    out["remaining30_bfo_msv"] = max(LIMITS_30D_MSV["bfo"] - out["organs"]["bfo"]["d30_msv"], 0.0)
    return out


# --------------------------------------------------------------------------- bone

# LeBlanc et al. 2000, long-duration flight without modern countermeasures, DXA areal BMD.
LEBLANC_PCT_PER_MONTH = {"lumbar spine": 1.06, "femoral neck": 1.15, "trochanter": 1.56}
DAYS_PER_MONTH = 30.44
ADHERENCE_WATCH, ADHERENCE_ACT = 0.8, 0.5     # of the prescribed resistive minutes. Team choice.


def bone(mission_day, resistive_minutes, prescribed_min, gravity_g=0.0, planned_days=None):
    """Projected bone loss with no countermeasure, and resistive-exercise adherence.

    The projection is the LeBlanc 2000 rate (no effective countermeasure), i.e. what is at
    stake if exercise lapses; it is not a measurement of this astronaut's bones. Partial
    gravity (Moon, Mars) has no flight data; the microgravity rate is used as an upper bound.
    """
    months = mission_day / DAYS_PER_MONTH
    proj = {site: -r * months for site, r in LEBLANC_PCT_PER_MONTH.items()}
    end = None
    if planned_days:
        end = {site: -r * planned_days / DAYS_PER_MONTH for site, r in LEBLANC_PCT_PER_MONTH.items()}
    last = [float(m) for m in resistive_minutes[-7:]]
    adherence = (float(np.mean([min(m / prescribed_min, 1.0) for m in last]))
                 if last and prescribed_min > 0 else None)
    status = OK
    if adherence is not None:
        status = ACT if adherence < ADHERENCE_ACT else WATCH if adherence < ADHERENCE_WATCH else OK
    notes = []
    if gravity_g > 0:
        notes.append("No flight data for partial gravity: the microgravity rate is an upper bound.")
    return {"projected_unprotected_pct": proj, "projected_end_pct": end, "adherence_7d": adherence,
            "days_logged": len(last), "status": status, "notes": notes}


# ------------------------------------------------------------------- environment

NASA_STD_CO2_MMHG = 3.0        # NASA-STD-3001 Vol. 2 [V2 6004]: 1-hour average ppCO2 <= 3 mmHg
HEADACHE_GUIDE_MMHG = 2.5      # NASA OCHMO: 7-day average < 2.5 mmHg keeps headache risk < 1%
LAW2014_OR_PER_MMHG = 2.0      # Law et al. 2014: odds of headache ~double per +1 mmHg


def co2(readings_mmhg, headaches_recent=False):
    """Cabin CO2 from the crew's readings (spot values, not 1-hour averages: stated)."""
    r = [float(x) for x in readings_mmhg if x is not None]
    if not r:
        return {"status": OK, "mean7_mmhg": None, "max_mmhg": None, "headache_odds_x": None,
                "headaches_recent": headaches_recent, "n": 0}
    last = r[-7:]
    mean7 = float(np.mean(last))
    odds = LAW2014_OR_PER_MMHG ** (mean7 - HEADACHE_GUIDE_MMHG)
    status = (ACT if max(last) > NASA_STD_CO2_MMHG or mean7 > NASA_STD_CO2_MMHG
              else WATCH if mean7 > HEADACHE_GUIDE_MMHG or headaches_recent else OK)
    return {"status": status, "mean7_mmhg": mean7, "max_mmhg": max(last), "headache_odds_x": odds,
            "headaches_recent": headaches_recent, "n": len(last)}


# ------------------------------------------------------------- personal baselines

Z_WATCH, Z_ACT = 2.0, 3.0      # statistical-process-control style limits. Team choice.
N_BASELINE = 5


def baseline_z(series, n_base=N_BASELINE, explicit=None, rel_floor=0.05):
    """z-score of the latest value against the astronaut's own baseline.

    Baseline = `explicit` {"mean","sd"} if given, else the first `n_base` values. The SD has a
    floor of `rel_floor` x |mean| so a very stable baseline does not turn noise into alarms.
    Returns None until a baseline exists and there is a later value to compare.
    """
    vals = [float(v) for v in series if v is not None and np.isfinite(v)]
    if explicit and explicit.get("mean") is not None:
        mean = float(explicit["mean"])
        sd = float(explicit.get("sd") or 0.0)
        later = vals
    else:
        if len(vals) <= n_base:
            return None
        base, later = vals[:n_base], vals[n_base:]
        mean, sd = float(np.mean(base)), float(np.std(base, ddof=1))
    if not later:
        return None
    sd = max(sd, rel_floor * abs(mean), 1e-9)
    return {"latest": later[-1], "mean": mean, "sd": sd, "z": (later[-1] - mean) / sd}


def z_status(z, direction):
    """direction +1: high is bad; -1: low is bad."""
    if z is None:
        return OK
    v = z["z"] * direction
    return ACT if v >= Z_ACT else WATCH if v >= Z_WATCH else OK


# -------------------------------------------------------------------------- heart

RR_MIN_MS, RR_MAX_MS, RR_JUMP = 300.0, 2000.0, 0.20   # artefact rules: physiological range, 20 % rule


def hrv(rr_ms):
    """Time-domain HRV from RR intervals (Task Force of the ESC/NASPE, 1996).

    Artefacts are removed first: intervals outside 300-2000 ms, and intervals that differ by
    more than 20 % from the previous accepted one. Needs >= 30 clean beats.
    """
    clean = []
    for x in rr_ms:
        x = float(x)
        if not RR_MIN_MS <= x <= RR_MAX_MS:
            continue
        if clean and abs(x - clean[-1]) > RR_JUMP * clean[-1]:
            continue
        clean.append(x)
    if len(clean) < 30:
        return None
    rr = np.array(clean)
    d = np.diff(rr)
    return {"rmssd_ms": float(np.sqrt(np.mean(d * d))), "sdnn_ms": float(np.std(rr, ddof=1)),
            "hr_bpm": float(60000.0 / rr.mean()), "beats": int(rr.size), "rejected": len(rr_ms) - int(rr.size)}


# ---------------------------------------------------------------------- cognition

PVTB_LAPSE_MS = 355.0      # Basner, Mollicone & Dinges 2011: PVT-B (3 min) lapse threshold
FALSE_START_MS = 100.0     # responses faster than 100 ms are false starts


def pvt(rts_ms, false_starts=0, duration_s=180.0):
    """Psychomotor Vigilance Test metrics. Reaction times in ms."""
    rts = [float(r) for r in rts_ms if r is not None]
    valid = [r for r in rts if r >= FALSE_START_MS]
    fs = int(false_starts) + sum(1 for r in rts if r < FALSE_START_MS)
    if not valid:
        return None
    a = np.array(valid)
    return {"n": int(a.size), "mean_rt_ms": float(a.mean()), "median_rt_ms": float(np.median(a)),
            "lapses": int((a >= PVTB_LAPSE_MS).sum()), "false_starts": fs,
            "speed": float(np.mean(1000.0 / a)), "duration_s": float(duration_s)}


# ------------------------------------------------------------------------- sleep

TAU_RISE_H = 18.2          # Process S build-up during wake (Daan, Beersma & Borbely 1984)
TAU_DECAY_H = 4.2          # Process S decline during sleep


def _s_wake_steady(sleep_h):
    """Process S at wake-up in steady state for a 24 h day with `sleep_h` of sleep."""
    a = math.exp(-(24.0 - sleep_h) / TAU_RISE_H)
    b = math.exp(-sleep_h / TAU_DECAY_H)
    return b * (1 - a) / (1 - a * b)


S_WAKE_REF = _s_wake_steady(8.0)
SLEEP_WATCH, SLEEP_ACT = _s_wake_steady(7.0) / S_WAKE_REF, _s_wake_steady(6.0) / S_WAKE_REF
#   i.e. the residual pressure of habitually sleeping < 7 h (watch) or < 6 h (act). Team choice.


def sleep_pressure(sleep_hours, wake_clock_h=None):
    """Two-process model, Process S only (Process C needs a measured circadian phase we don't have).

    Each day: wake for 24 - sleep_h hours (S rises toward 1), then sleep for sleep_h hours
    (S decays toward 0). Starts from the 8 h steady state. Index = S at the latest wake-up /
    S at wake after habitual 8 h sleep: 1.0 = fully recovered, higher = carried-over pressure.
    Circadian disruption proxy: spread (SD) of wake-up clock times over the last 7 days.
    """
    hrs = [float(h) for h in sleep_hours if h is not None]
    if not hrs:
        return None
    s = S_WAKE_REF
    for h in hrs:
        h = min(max(h, 0.0), 24.0)
        s = 1 - (1 - s) * math.exp(-(24.0 - h) / TAU_RISE_H)     # wake
        s = s * math.exp(-h / TAU_DECAY_H)                          # sleep
    index = s / S_WAKE_REF
    status = ACT if index >= SLEEP_ACT else WATCH if index >= SLEEP_WATCH else OK
    out = {"index": index, "s_wake": s, "mean_sleep_7d_h": float(np.mean(hrs[-7:])), "status": status,
           "watch_at": SLEEP_WATCH, "act_at": SLEEP_ACT, "wake_spread_h": None}
    wk = [float(w) for w in (wake_clock_h or []) if w is not None][-7:]
    if len(wk) >= 3:
        ang = np.array(wk) / 24.0 * 2 * np.pi                      # circular SD of clock times
        r = np.hypot(np.cos(ang).mean(), np.sin(ang).mean())
        spread = float(np.sqrt(-2 * np.log(max(r, 1e-12))) * 24.0 / (2 * np.pi))
        out["wake_spread_h"] = spread
        if spread > 1.5 and status == OK:                          # > 1.5 h shifting. Team choice.
            out["status"] = WATCH
    return out
