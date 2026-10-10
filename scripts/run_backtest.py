"""Backtest SHELTER's decision rules on every cached historical storm.

    python scripts/run_backtest.py            # default thresholds
    python scripts/run_backtest.py --shelter 2 --eva-bfo 1

Prints one row per storm and writes data/backtest_results.csv. These are the
numbers to quote in the pitch, with the thresholds used.
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shelter import config                     # noqa: E402
from shelter.data import events                # noqa: E402
from shelter.planner import engine             # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shelter", type=float, default=engine.Policy.shelter_trigger_msv,
                    help="shelter trigger: projected cabin BFO mSv over the horizon")
    ap.add_argument("--eva-bfo", type=float, default=engine.Policy.eva_start_bfo_msv)
    ap.add_argument("--include-synthetic", action="store_true")
    a = ap.parse_args()
    policy = engine.Policy(shelter_trigger_msv=a.shelter, eva_start_bfo_msv=a.eva_bfo)

    rows = []
    for ev in events.availability():
        if not ev["cached"] or (ev.get("synthetic") and not a.include_synthetic):
            continue
        series, _, _ = events.load_event(ev["id"], with_markers=False)
        p = engine.prepare(series)
        window = float(p.hours[-1] - p.hours[p.t0_index])
        r = engine.backtest(p, engine.default_schedule(window), policy)
        h, s = r["bounds"]["hard"], r["bounds"]["soft"]
        evas = r["evas"]
        rows.append({
            "event": ev["id"], "title": ev["title"],
            "baseline_bfo_msv": round(h["baseline"]["bfo"], 2), "shelter_bfo_msv": round(h["policy"]["bfo"], 2),
            "saved_bfo_msv": round(h["saved"]["bfo"], 2), "saved_bfo_soft_msv": round(s["saved"]["bfo"], 2),
            "saved_pct": round(100 * h["saved"]["bfo"] / h["baseline"]["bfo"], 1) if h["baseline"]["bfo"] > 0 else 0.0,
            "baseline_skin_msv": round(h["baseline"]["skin"], 1), "shelter_skin_msv": round(h["policy"]["skin"], 1),
            "eva_delay_h": round(sum(e["delay_h"] for e in evas), 1),
            "evas_cancelled": sum(e["policy_outcome"] == "cancelled" for e in evas),
            "evas_terminated": sum(e["policy_outcome"] == "terminated" for e in evas),
            "shelter_h": round(r["shelter_hours"], 1), "false_alarms": r["false_alarms"]["count"],
            "first_s1_utc": r["first_s1_utc"],
            "first_action_utc": (r["first_action"] or {}).get("utc"),
        })
    if not rows:
        print("No cached storms. Run: python scripts/fetch_data.py")
        return 1
    cols = ["event", "baseline_bfo_msv", "shelter_bfo_msv", "saved_pct", "eva_delay_h", "evas_cancelled",
            "shelter_h", "false_alarms"]
    print(" ".join(f"{c:>16s}" for c in cols))
    for r in rows:
        print(" ".join(f"{str(r[c]):>16s}" for c in cols))
    tb = sum(r["baseline_bfo_msv"] for r in rows)
    ts = sum(r["shelter_bfo_msv"] for r in rows)
    print(f"\nAll storms: BFO dose {tb:.1f} -> {ts:.1f} mSv ({100 * (tb - ts) / tb if tb else 0:.0f}% less), "
          f"{sum(r['false_alarms'] for r in rows)} false alarms, "
          f"{sum(r['eva_delay_h'] for r in rows):.0f} h of EVA delay.")
    print(f"Thresholds: shelter at {policy.shelter_trigger_msv} mSv, EVA start limit {policy.eva_start_bfo_msv} mSv BFO.")
    out = config.ROOT / "data" / "backtest_results.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"Saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
