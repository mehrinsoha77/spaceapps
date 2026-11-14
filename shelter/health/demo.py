"""A SYNTHETIC 40-day crew log for demonstrating the health monitor.

Not real astronaut data. It is generated (fixed seed) to show each indicator moving:
a solar-storm shelter period (days 18-24) with short, shifted sleep, higher stress,
slower reaction times and a higher heart rate; a storm dose on day 21; cabin CO2
creeping above the standard from day 30; resistive exercise lapsing in the last
10 days; and a cold sore on day 37. The UI shows a red SYNTHETIC banner with it.
"""

import numpy as np

DAYS = 40
STORM = range(18, 25)


def _rr(rng, hr, rmssd, n=90):
    """RR intervals (ms) with a given mean heart rate and beat-to-beat variability."""
    mean = 60000.0 / hr
    sd_step = rmssd / np.sqrt(2.0)
    rr = mean + rng.normal(0, sd_step, n)          # independent beats: RMSSD ~ sd_step * sqrt(2)
    return [round(float(x), 1) for x in rr]


def _pvt(rng, median_ms, tail):
    n = 60
    rts = rng.lognormal(np.log(median_ms), 0.12, n)
    k = int(tail)
    if k:
        rts[rng.choice(n, k, replace=False)] = rng.uniform(380, 900, k)   # lapses
    return {"rts": [round(float(x), 1) for x in rts], "false_starts": int(rng.integers(0, 2)),
            "duration_s": 180, "protocol": "pvt-b"}


def demo_log(seed=7):
    rng = np.random.default_rng(seed)
    checkins = []
    for d in range(1, DAYS + 1):
        storm = d in STORM
        late = d > 30
        c = {
            "day": d,
            "sleep_h": round(float(rng.normal(5.4 if storm else 7.9, 0.3)), 1),
            "wake_clock_h": round(float((7.0 + (rng.uniform(-3, 4) if storm else rng.normal(0, 0.3))) % 24), 1),
            "mood": int(np.clip(round(rng.normal(4.5 if storm else 7.2, 0.6)), 0, 10)),
            "stress": int(np.clip(round(rng.normal(7.0 if storm else 3.0, 0.6)), 0, 10)),
            "resistive_min": int(max(0, rng.normal(22 if late else 58, 5))) if not storm else 0,
            "co2_mmhg": round(float(2.2 + (0.13 * (d - 29) if d >= 30 else 0) + rng.normal(0, 0.08)), 2),
            "resting_hr": round(float(rng.normal(67 if storm else 58, 1.5)), 0),
            "symptoms": [],
        }
        c["rr_ms"] = _rr(rng, c["resting_hr"], 24.0 if storm else 46.0)
        if d % 3 == 1 or d in (20, 22):
            c["pvt"] = _pvt(rng, 300 if storm else 245, 10 if storm else int(rng.integers(0, 3)))
        if d in (36, 39):
            c["symptoms"].append("headache")
        if d == 37:
            c["symptoms"].append("cold_sore")
        checkins.append(c)
    return {
        "synthetic": True,
        "profile": {"name": "Demo astronaut (SYNTHETIC)", "gravity_g": 0.0, "gcr_msv_per_day": 1.75,
                    "prior_career_msv": 40.0, "resistive_prescribed_min": 60, "planned_days": 180},
        "radiation_events": [{"day": 21, "bfo": 14.0, "eye": 31.0, "skin": 118.0,
                              "label": "Solar storm, sheltered (SYNTHETIC values)"}],
        "checkins": checkins,
    }
