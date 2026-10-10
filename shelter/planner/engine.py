"""SHELTER decision engine and no-look-ahead backtest.

At every data step the engine sees ONLY data up to that time. It projects the
dose for the next hours with two transparent scenarios:

  high  ("still rising"):  rate_now * exp(k*tau), capped at growth_cap x rate_now,
                            where k is the log-slope of the >=10 MeV SEP flux over
                            the last `trend_h` hours (only if k > 0)
  low   ("decaying"):       rate_now * exp(-tau / decay_h)

Decisions use the HIGH scenario (conservative). These are heuristics, not
forecasts from a physics model; the backtest measures how well they work.

The crew member's location each hour is one of: cabin, shelter, eva.
Baseline = follow the schedule exactly and never shelter.
Policy   = apply the rules below.
Both are then scored with the dose that actually happened.
"""

from dataclasses import asdict, dataclass, field

import numpy as np

from ..physics import dose as dose_mod
from ..physics.limits import GCR_CRUISE_MSV_PER_DAY, s_level
from ..data.series import dose_channels, sep_flux

TARGETS = ("skin", "eye", "bfo")
PLACES = ("cabin", "shelter", "eva")


@dataclass
class Policy:
    # projection
    trend_h: float = 3.0
    horizon_h: float = 12.0
    growth_cap: float = 10.0
    decay_h: float = 24.0
    # storm shelter
    shelter_trigger_msv: float = 1.0      # projected cabin BFO dose-eq over horizon (high) -> shelter
    shelter_exit_rate_msv_h: float = 0.02 # leave when cabin BFO rate below this ...
    shelter_exit_quiet_h: int = 3         # ... for this many consecutive steps, and not rising
    # EVA
    eva_start_bfo_msv: float = 0.5        # don't start if projected EVA BFO dose-eq (high) >= this
    eva_start_skin_msv: float = 5.0
    eva_block_if_s1_rising: bool = True   # don't start while >=10 MeV >= 10 pfu and rising
    eva_abort_bfo_msv: float = 1.0        # terminate if projected remaining EVA BFO dose (high) >= this
    eva_abort_skin_msv: float = 10.0
    # scoring
    false_alarm_msv: float = 0.1          # an action that saved less than this was unnecessary
    steepening_for_decisions: float = 0.0 # 0 = conservative upper-bound spectrum


@dataclass
class Activity:
    id: str
    kind: str                 # EVA | BURN
    start_h: float            # hours after replay start
    duration_h: float
    max_delay_h: float = 48.0
    ingress_min: float = 30.0 # EVA only: time to get back inside after a terminate call


@dataclass
class Prepared:
    """Everything the engine needs, computed once per series."""
    hours: np.ndarray
    times_iso: list
    j10: np.ndarray                    # SEP >=10 MeV flux (background removed)
    raw10: np.ndarray                  # raw >=10 MeV flux (for S-scale)
    rates: dict                        # rates[spectrum][place][target] -> (T,) mSv/h; spectrum = hard|soft
    t0_index: int                      # first index of the replay window (after lead-in)
    energies: list = field(default_factory=list)
    sep: np.ndarray = None


LOCATION_FOR_PLACE = {"cabin": "cabin", "shelter": "shelter", "eva": "eva"}


def prepare(series, locations=None, t0=None):
    """Background-subtract, compute dose-rate series for every place/target/bound."""
    locations = locations or dose_mod.LOCATIONS
    sep, _ = sep_flux(series)
    d_e, d_sep = dose_channels(series.energies, sep)
    rates = {}
    for bound, steep in (("hard", 0.0), ("soft", 1.0)):
        rates[bound] = {}
        for place in PLACES:
            loc = locations[LOCATION_FOR_PLACE[place]]
            ds = dose_mod.dose_rates(d_e, d_sep, loc.shielding, steepening=steep)
            rates[bound][place] = {t: np.nan_to_num(ds.rate_msv_h[t]) for t in TARGETS}
    hours = series.hours
    if t0 is None:
        t0_index = int(np.searchsorted(hours, 168.0)) if hours[-1] > 168 else 0
    else:
        t0_index = int(np.searchsorted(series.times, np.datetime64(t0)))
    ref = series.energies.index(10.0)
    return Prepared(hours=hours, times_iso=series.iso_times(), j10=np.nan_to_num(sep[:, ref]),
                    raw10=series.flux[:, ref], rates=rates, t0_index=t0_index,
                    energies=list(series.energies), sep=sep)


# ---------------------------------------------------------------- nowcast

def trend_rate(p, i, policy):
    """Log-slope (1/h) of SEP >=10 MeV flux over the trailing window. Uses data <= i only."""
    h = p.hours
    j = p.j10
    k0 = int(np.searchsorted(h, h[i] - policy.trend_h))
    if k0 >= i or j[i] <= 0 or j[k0] <= 0:
        return 0.0
    return float(np.log(j[i] / j[k0]) / max(h[i] - h[k0], 1e-6))


def projected_dose(rate_now, k, a, b, policy, scenario="high"):
    """Integral of the projected rate from a to b hours ahead (a<b), closed form."""
    if b <= a or rate_now <= 0:
        return 0.0
    if scenario == "high" and k > 0:
        t_cap = np.log(policy.growth_cap) / k
        dose = 0.0
        a1, b1 = a, min(b, t_cap)
        if b1 > a1:
            dose += rate_now * (np.exp(k * b1) - np.exp(k * a1)) / k
        a2 = max(a, t_cap)
        if b > a2:
            dose += rate_now * policy.growth_cap * (b - a2)
        return float(dose)
    if scenario == "high":
        return float(rate_now * (b - a))                     # persistence
    tau = policy.decay_h
    return float(rate_now * tau * (np.exp(-a / tau) - np.exp(-b / tau)))


def nowcast(p, i, policy):
    k = trend_rate(p, i, policy)
    r = p.rates["hard" if policy.steepening_for_decisions == 0 else "soft"]
    now = {place: {t: float(r[place][t][i]) for t in TARGETS} for place in PLACES}
    return {
        "k_per_h": k,
        "rising": k > 0.05,
        "j10_sep": float(p.j10[i]),
        "j10_raw": None if np.isnan(p.raw10[i]) else float(p.raw10[i]),
        "s_level": s_level(None if np.isnan(p.raw10[i]) else float(p.raw10[i])),
        "rate_now": now,
    }


# ---------------------------------------------------------------- simulation

def run(p, schedule, policy=None, apply_policy=True):
    """Simulate one crew member through the replay window.

    Returns per-step locations, decision log and per-activity outcomes.
    Decisions at step i use only p.* values at indices <= i.
    """
    policy = policy or Policy()
    acts = [dict(asdict(a) if isinstance(a, Activity) else a) for a in schedule]
    for a in acts:
        a.update(state="planned", planned_start=a["start_h"], actual_start=None,
                 actual_end=None, delay_h=0.0, outcome=None)
    i0 = p.t0_index
    h_rel = p.hours - p.hours[i0]
    n = len(p.hours)
    place = np.array(["cabin"] * n, dtype=object)
    eva_frac = np.zeros(n)          # fraction of step spent on EVA (ingress partial steps)
    log = []
    sheltered = False
    quiet_steps = 0

    def note(i, action, reason, extra=None):
        log.append({"i": i, "t_h": round(float(h_rel[i]), 2), "utc": p.times_iso[i],
                    "action": action, "reason": reason, **(extra or {})})

    for i in range(i0, n - 1):
        h = h_rel[i]
        dt = h_rel[i + 1] - h
        nc = nowcast(p, i, policy)
        k = nc["k_per_h"]
        rn = nc["rate_now"]
        burn = next((a for a in acts if a["kind"] == "BURN" and a["state"] == "running"), None)

        # ---- start / defer activities whose (possibly delayed) start time has come
        for a in acts:
            if a["state"] != "planned" or h + 1e-9 < a["planned_start"] + a["delay_h"]:
                continue
            if a["kind"] == "BURN":
                a.update(state="running", actual_start=h)
                cost = projected_dose(rn["cabin"]["bfo"], k, 0, a["duration_h"], policy) - \
                    projected_dose(rn["shelter"]["bfo"], k, 0, a["duration_h"], policy)
                msg = "Burn is non-interruptible; crew stays at station."
                if sheltered:
                    msg += f" Crew leaves shelter for the burn (projected extra BFO dose {max(cost, 0):.2f} mSv)."
                note(i, "BURN_START", msg)
                continue
            # EVA start decision
            proj_bfo = projected_dose(rn["eva"]["bfo"], k, 0, a["duration_h"], policy)
            proj_skin = projected_dose(rn["eva"]["skin"], k, 0, a["duration_h"], policy)
            s1_rising = (nc["j10_raw"] or 0) >= 10 and nc["rising"]
            block = apply_policy and (proj_bfo >= policy.eva_start_bfo_msv
                                      or proj_skin >= policy.eva_start_skin_msv
                                      or (policy.eva_block_if_s1_rising and s1_rising)
                                      or sheltered)
            if block:
                if a["delay_h"] + dt > a["max_delay_h"]:
                    a.update(state="cancelled", outcome="cancelled")
                    note(i, "EVA_CANCEL", f"{a['id']}: still unsafe after max delay "
                                          f"{a['max_delay_h']:.0f} h.", {"activity": a["id"]})
                else:
                    if a["delay_h"] == 0:
                        why = []
                        if proj_bfo >= policy.eva_start_bfo_msv:
                            why.append(f"projected EVA BFO {proj_bfo:.2f} mSv >= {policy.eva_start_bfo_msv}")
                        if proj_skin >= policy.eva_start_skin_msv:
                            why.append(f"projected EVA skin {proj_skin:.1f} mSv >= {policy.eva_start_skin_msv}")
                        if policy.eva_block_if_s1_rising and s1_rising:
                            why.append(f">=10 MeV at {nc['j10_raw']:.0f} pfu ({nc['s_level']}) and rising")
                        if sheltered:
                            why.append("crew is in storm shelter")
                        note(i, "EVA_DEFER", f"{a['id']}: " + "; ".join(why), {"activity": a["id"],
                             "proj_bfo_msv": round(proj_bfo, 3), "proj_skin_msv": round(proj_skin, 2)})
                    a["delay_h"] += dt
            else:
                a.update(state="running", actual_start=h)
                note(i, "EVA_START", f"{a['id']}: projected EVA BFO {proj_bfo:.2f} mSv, skin {proj_skin:.1f} mSv"
                     + (f" (after {a['delay_h']:.0f} h delay)" if a["delay_h"] else ""), {"activity": a["id"]})

        # re-read: a burn may have started this step
        burn = next((a for a in acts if a["kind"] == "BURN" and a["state"] == "running"), None)

        # ---- running EVA: terminate?
        eva = next((a for a in acts if a["kind"] == "EVA" and a["state"] == "running"), None)
        if eva is not None:
            remaining = eva["actual_start"] + eva["duration_h"] - h
            if remaining <= 1e-9:
                eva.update(state="done", actual_end=h, outcome=eva.get("outcome") or "completed")
                eva = None
            elif apply_policy:
                rb = projected_dose(rn["eva"]["bfo"], k, 0, remaining, policy)
                rs = projected_dose(rn["eva"]["skin"], k, 0, remaining, policy)
                if rb >= policy.eva_abort_bfo_msv or rs >= policy.eva_abort_skin_msv:
                    ingress_h = eva["ingress_min"] / 60.0
                    eva.update(state="done", actual_end=h + ingress_h, outcome="terminated",
                               lost_h=round(remaining - ingress_h, 2))
                    note(i, "EVA_TERMINATE", f"{eva['id']}: projected remaining EVA dose BFO {rb:.2f} / "
                         f"skin {rs:.1f} mSv. Ingress {eva['ingress_min']:.0f} min.", {"activity": eva["id"]})
                    eva_frac[i] = min(ingress_h / dt, 1.0) if dt > 0 else 0
                    place[i] = "shelter" if sheltered else "cabin"
                    eva = None
                    # an EVA abort is also a strong shelter signal; handled below
        # ---- burns end
        if burn is not None and h + 1e-9 >= burn["actual_start"] + burn["duration_h"]:
            burn.update(state="done", actual_end=h, outcome="completed")
            note(i, "BURN_END", "Burn complete.")
            burn = None

        # ---- storm shelter
        if apply_policy and eva is None:
            proj_cabin = projected_dose(rn["cabin"]["bfo"], k, 0, policy.horizon_h, policy)
            if not sheltered and proj_cabin >= policy.shelter_trigger_msv:
                if burn is not None:
                    if not any(e["action"] == "SHELTER_BLOCKED" and e["i"] >= i - 1 for e in log):
                        note(i, "SHELTER_BLOCKED", "Shelter needed but burn in progress: finish burn first.",
                             {"proj_cabin_bfo_msv": round(proj_cabin, 2)})
                else:
                    sheltered = True
                    quiet_steps = 0
                    note(i, "SHELTER_ENTER", f"Projected cabin BFO dose {proj_cabin:.2f} mSv over next "
                         f"{policy.horizon_h:.0f} h >= {policy.shelter_trigger_msv} mSv.",
                         {"proj_cabin_bfo_msv": round(proj_cabin, 2)})
            elif sheltered:
                if rn["cabin"]["bfo"] < policy.shelter_exit_rate_msv_h and not nc["rising"]:
                    quiet_steps += 1
                else:
                    quiet_steps = 0
                if quiet_steps >= policy.shelter_exit_quiet_h:
                    sheltered = False
                    note(i, "SHELTER_EXIT", f"Cabin BFO rate below {policy.shelter_exit_rate_msv_h} mSv/h "
                         f"for {policy.shelter_exit_quiet_h} steps and not rising.")

        # ---- where is the crew member during [i, i+1)?
        if eva is not None:
            place[i] = "eva"
            eva_frac[i] = 1.0
        elif eva_frac[i] == 0:
            place[i] = "shelter" if (sheltered and burn is None) else "cabin"

    for a in acts:
        if a["state"] == "planned":
            a.update(state="not_reached", outcome="not reached (window ended)")
        elif a["state"] == "running":
            a.update(state="done", outcome="completed (window ended)")
    return {"place": place, "eva_frac": eva_frac, "log": log, "activities": acts}


def score(p, sim, bound="hard"):
    """Dose actually received along a simulated timeline (SEP only), per target."""
    i0 = p.t0_index
    h = p.hours
    r = p.rates[bound]
    tot = {t: 0.0 for t in TARGETS}
    cum = {t: [0.0] for t in TARGETS}
    for i in range(i0, len(h) - 1):
        dt = h[i + 1] - h[i]
        pl = sim["place"][i]
        f = sim["eva_frac"][i]
        for t in TARGETS:
            avg = lambda place: 0.5 * (r[place][t][i] + r[place][t][i + 1])
            if f > 0 and pl != "eva":
                d = (f * avg("eva") + (1 - f) * avg(pl)) * dt
            else:
                d = avg(pl) * dt
            tot[t] += d
            cum[t].append(cum[t][-1] + d)
    return tot, cum


def backtest(p, schedule, policy=None):
    """Run baseline and policy timelines through the same real data and compare."""
    policy = policy or Policy()
    base = run(p, schedule, policy, apply_policy=False)
    pol = run(p, schedule, policy, apply_policy=True)
    out = {"bounds": {}}
    for bound in ("hard", "soft"):
        bt, bc = score(p, base, bound)
        pt, pc = score(p, pol, bound)
        out["bounds"][bound] = {"baseline": bt, "policy": pt,
                                "saved": {t: bt[t] - pt[t] for t in TARGETS},
                                "cum_baseline": bc, "cum_policy": pc}
    i0 = p.t0_index
    window_h = float(p.hours[-1] - p.hours[i0])
    gcr = GCR_CRUISE_MSV_PER_DAY * window_h / 24.0

    # EVA bookkeeping
    eva_rows = []
    for a_b, a_p in zip(base["activities"], pol["activities"]):
        if a_p["kind"] != "EVA":
            continue
        eva_rows.append({
            "id": a_p["id"], "planned_start_h": a_p["planned_start"], "duration_h": a_p["duration_h"],
            "baseline_outcome": a_b["outcome"], "policy_outcome": a_p["outcome"],
            "delay_h": round(a_p["delay_h"], 2), "lost_h": a_p.get("lost_h", 0.0),
        })
    # false alarms: actions whose hindsight benefit was tiny
    false_alarms = _false_alarms(p, base, pol, policy)
    shelter_h = float(sum(p.hours[i + 1] - p.hours[i] for i in range(i0, len(p.hours) - 1)
                          if pol["place"][i] == "shelter"))
    first_s1 = next((i for i in range(i0, len(p.hours)) if (np.nan_to_num(p.raw10[i]) >= 10)), None)
    first_action = next((e for e in pol["log"] if e["action"] in ("EVA_DEFER", "EVA_TERMINATE", "SHELTER_ENTER")), None)
    out.update({
        "window_h": window_h,
        "gcr_msv": gcr,
        "evas": eva_rows,
        "shelter_hours": shelter_h,
        "false_alarms": false_alarms,
        "log": pol["log"],
        "first_s1_utc": p.times_iso[first_s1] if first_s1 is not None else None,
        "first_action": first_action,
        "place_policy": list(pol["place"][i0:]),
        "place_baseline": list(base["place"][i0:]),
    })
    return out


def _false_alarms(p, base, pol, policy):
    """Count shelter episodes and EVA deferrals that, in hindsight, avoided < false_alarm_msv."""
    r = p.rates["hard"]
    h = p.hours
    i0 = p.t0_index
    count, details = 0, []
    # shelter episodes
    i = i0
    while i < len(h) - 1:
        if pol["place"][i] == "shelter":
            j = i
            while j < len(h) - 1 and pol["place"][j] == "shelter":
                j += 1
            avoided = sum((r["cabin"]["bfo"][k] - r["shelter"]["bfo"][k]) * (h[k + 1] - h[k]) for k in range(i, j))
            if avoided < policy.false_alarm_msv:
                count += 1
                details.append({"kind": "shelter", "from_utc": p.times_iso[i], "hours": float(h[j] - h[i]),
                                "avoided_bfo_msv": round(float(avoided), 4)})
            i = j
        else:
            i += 1
    # EVA deferrals: dose the EVA would have had at its original time
    for a_b, a_p in zip(base["activities"], pol["activities"]):
        if a_p["kind"] != "EVA" or a_p["delay_h"] <= 0:
            continue
        s = a_p["planned_start"]
        idx = [k for k in range(i0, len(h) - 1) if s <= h[k] - h[i0] < s + a_p["duration_h"]]
        would = sum(r["eva"]["bfo"][k] * (h[k + 1] - h[k]) for k in idx)
        if would < policy.false_alarm_msv:
            count += 1
            details.append({"kind": "eva_defer", "activity": a_p["id"], "would_have_bfo_msv": round(float(would), 4)})
    return {"count": count, "details": details}


def default_schedule(window_h):
    """A plausible schedule: EVAs every ~2 days at 09:00 mission time, one burn."""
    acts = []
    k = 1
    start = 9.0
    while start + 6 < window_h:
        acts.append(Activity(f"EVA-{k}", "EVA", start, 6.0, max_delay_h=48.0, ingress_min=30.0))
        start += 48.0
        k += 1
    if window_h > 60:
        acts.append(Activity("BURN-1", "BURN", 58.0, 1.0, max_delay_h=0.0))
    return acts


def advise(p, i, policy=None, eva_duration_h=6.0):
    """Live advice at step i (latest data): EVA go/no-go, shelter call, time-to-threshold."""
    policy = policy or Policy()
    nc = nowcast(p, i, policy)
    k, rn = nc["k_per_h"], nc["rate_now"]
    out = {"nowcast": nc, "items": []}
    proj = {sc: {"bfo": projected_dose(rn["eva"]["bfo"], k, 0, eva_duration_h, policy, sc),
                 "skin": projected_dose(rn["eva"]["skin"], k, 0, eva_duration_h, policy, sc)}
            for sc in ("high", "low")}
    s1_rising = (nc["j10_raw"] or 0) >= 10 and nc["rising"]
    reasons = []
    if proj["high"]["bfo"] >= policy.eva_start_bfo_msv:
        reasons.append(f"projected EVA BFO {proj['high']['bfo']:.2f} mSv >= {policy.eva_start_bfo_msv}")
    if proj["high"]["skin"] >= policy.eva_start_skin_msv:
        reasons.append(f"projected EVA skin {proj['high']['skin']:.1f} mSv >= {policy.eva_start_skin_msv}")
    if policy.eva_block_if_s1_rising and s1_rising:
        reasons.append(f">=10 MeV flux {nc['j10_raw']:.0f} pfu ({nc['s_level']}) and rising")
    out["items"].append({
        "kind": "EVA", "verdict": "NO-GO" if reasons else "GO",
        "text": ("Hold EVA start: " + "; ".join(reasons)) if reasons else
                f"EVA of {eva_duration_h:g} h within flight-rule thresholds.",
        "projected": proj})
    cabin = {sc: projected_dose(rn["cabin"]["bfo"], k, 0, policy.horizon_h, policy, sc) for sc in ("high", "low")}
    shel = {sc: projected_dose(rn["shelter"]["bfo"], k, 0, policy.horizon_h, policy, sc) for sc in ("high", "low")}
    go_shelter = cabin["high"] >= policy.shelter_trigger_msv
    out["items"].append({
        "kind": "SHELTER", "verdict": "SHELTER" if go_shelter else "STAY",
        "text": (f"Move to storm shelter: projected cabin BFO dose {cabin['high']:.2f} mSv over "
                 f"{policy.horizon_h:g} h (shelter: {shel['high']:.2f} mSv).") if go_shelter else
                f"Cabin OK: projected BFO dose {cabin['high']:.3f} mSv over {policy.horizon_h:g} h.",
        "projected_cabin": cabin, "projected_shelter": shel})
    # minutes until an ongoing EVA reaches the abort threshold (high scenario)
    mins = None
    if rn["eva"]["bfo"] > 0:
        lo, hi = 0.0, 48.0
        if projected_dose(rn["eva"]["bfo"], k, 0, hi, policy) >= policy.eva_abort_bfo_msv:
            for _ in range(50):
                mid = 0.5 * (lo + hi)
                if projected_dose(rn["eva"]["bfo"], k, 0, mid, policy) >= policy.eva_abort_bfo_msv:
                    hi = mid
                else:
                    lo = mid
            mins = hi * 60
    out["items"].append({
        "kind": "EVA_IN_PROGRESS",
        "verdict": "OK" if mins is None or mins > 120 else "TERMINATE" if mins < 60 else "PREPARE",
        "text": ("No abort threshold reached within 48 h at current conditions." if mins is None else
                 f"An EVA in progress would reach the {policy.eva_abort_bfo_msv} mSv BFO abort threshold in "
                 f"~{mins:.0f} min (high scenario)."),
        "minutes_to_abort_threshold": mins})
    return out
