"""Download and cache every dataset SHELTER needs, then check it.

Run this while online (it takes a minute or two):
    python scripts/fetch_data.py
Afterwards the app works with no internet:  SHELTER_OFFLINE=1 python -m shelter.server.app

    python scripts/fetch_data.py --bundle
also copies the historical data into data/bundled/ (about 2 MB). Commit that folder
and every deployment (e.g. Vercel) replays the storms without contacting NASA.
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shelter import config                      # noqa: E402
from shelter.data import events, swpc           # noqa: E402
from shelter.data.http import DataUnavailable   # noqa: E402
from shelter.validation import rad              # noqa: E402


def bundle(log=print):
    """Copy cached OMNI2 years and DONKI markers for the catalog storms into data/bundled/."""
    n = 0
    for src in sorted((config.CACHE_DIR / "omni").glob("omni2_*_protons.npz")):
        dst = config.BUNDLED_DIR / "omni" / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
    for ev in events.EVENTS:
        d = config.CACHE_DIR / "events" / ev["id"]
        for src in sorted(d.glob("donki_*.json")) if d.is_dir() else []:
            if src.name.endswith(".meta.json"):
                continue
            dst = config.BUNDLED_DIR / "events" / ev["id"] / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    size = sum(f.stat().st_size for f in config.BUNDLED_DIR.rglob("*") if f.is_file())
    log(f"Bundled {n} files into {config.BUNDLED_DIR} ({size / 1e6:.1f} MB). Commit that folder to deploy with data.")
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", action="store_true", help="also copy the data into data/bundled/ for deployment")
    args = ap.parse_args()
    if config.OFFLINE:
        print("SHELTER_OFFLINE=1 is set; unset it to download.")
        return 2
    print(f"Cache folder: {config.CACHE_DIR}")
    print(f"NASA API key: {'DEMO_KEY (rate-limited; get a free key at api.nasa.gov)' if config.NASA_API_KEY == 'DEMO_KEY' else 'set'}\n")

    print("1/3  Historical storms (NASA SPDF OMNI2 + NASA DONKI)")
    res = events.prefetch()
    failed = [k for k, v in res.items() if not v["ok"]]

    print("\n2/3  Live GOES protons (NOAA SWPC)")
    try:
        s, meta = swpc.load_live()
        print(f"[ok]   {s.times.size} samples, latest {s.times[-1]}Z, source: {meta['source']}")
    except (DataUnavailable, ValueError) as exc:
        print(f"[FAIL] live feed: {exc}")
        failed.append("live")

    print("\n3/3  MSL/RAD benchmark")
    try:
        b = rad.run_benchmark()
        print(f"{'storm':40s} {'RAD mSv':>8s} {'SHELTER mSv':>16s} {'ratio':>7s} {'leave-one-out':>14s}")
        for r in b["rows"]:
            print(f"{r['title']:40s} {r['measured_msv']:8.1f} "
                  f"{r['predicted_min_msv']:7.1f}-{r['predicted_max_msv']:<7.1f} {r['ratio_mid']:7.2f} "
                  f"{r.get('loo_prediction_msv', float('nan')):9.1f} mSv")
        print(f"Typical error factor: x{b['typical_factor_error']:.2f}")
    except (DataUnavailable, ValueError, KeyError) as exc:
        print(f"[FAIL] benchmark: {exc}")
        failed.append("benchmark")

    if args.bundle:
        print("\nBundle for deployment")
        bundle()

    print("\nDone." if not failed else f"\nDone with problems: {', '.join(failed)}. Re-run to retry; cached items are kept.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
