"""NOAA SWPC real-time GOES integral protons (5-minute cadence, last 7 days).

Record format (checked against the live feed):
  {"time_tag": "2026-10-10T08:00:00Z", "satellite": 18, "flux": 0.32, "energy": ">=10 MeV"}
"""

import numpy as np

from .. import config
from .http import fetch_json
from .series import FluxSeries

LIVE_ENERGIES = [1.0, 5.0, 10.0, 30.0, 50.0, 60.0, 100.0, 500.0]


def parse_swpc(records):
    by_time = {}
    for r in records:
        try:
            e = float(str(r["energy"]).replace(">=", "").replace("MeV", "").strip())
        except (KeyError, ValueError):
            continue
        if e not in LIVE_ENERGIES:
            continue
        t = str(r["time_tag"]).replace("Z", "")
        flux = r.get("flux")
        by_time.setdefault(t, {})[e] = np.nan if flux is None else float(flux)
    if not by_time:
        raise ValueError("SWPC feed contained no usable proton records")
    keys = sorted(by_time)
    times = np.array(keys, dtype="datetime64[s]")
    flux = np.array([[by_time[k].get(e, np.nan) for e in LIVE_ENERGIES] for k in keys])
    return times, flux


def load_live():
    records, meta = fetch_json(config.SWPC_PROTONS_URL, config.CACHE_DIR / "live" / "swpc_protons_7d.json",
                               max_age_s=240)
    times, flux = parse_swpc(records)
    series = FluxSeries(times, list(LIVE_ENERGIES), flux, source="NOAA SWPC GOES primary, integral protons (5-min)")
    return series, meta
