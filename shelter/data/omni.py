"""NASA SPDF OMNI2 hourly data: proton fluxes >1, >2, >4, >10, >30, >60 MeV.

Format (from omni2.text, the official format description): 55 whitespace-
separated words per hour. Word 1 = year, 2 = day of year, 3 = hour,
words 43-48 = proton flux (1/(cm^2 s sr)) above 1, 2, 4, 10, 30, 60 MeV.
Fill values: 999999.99 (word 43) and 99999.99 (words 44-48).
"""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .. import config
from .http import fetch_bytes
from .series import FluxSeries

OMNI_ENERGIES = [1.0, 2.0, 4.0, 10.0, 30.0, 60.0]
N_WORDS = 55
PROTON_WORDS = slice(42, 48)   # 0-based slice of words 43..48
# Fill values per word (omni2.text): F10.2 for >1 MeV, F9.2 for the rest.
FILL = np.array([999999.99, 99999.99, 99999.99, 99999.99, 99999.99, 99999.99])


class OmniFormatError(ValueError):
    pass


def parse_omni2(text, year=None):
    """Parse an OMNI2 yearly file. Returns (times datetime64[s], flux (T,6))."""
    times, rows, bad = [], [], 0
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        parts = ln.split()
        if len(parts) != N_WORDS:
            bad += 1
            continue
        y, doy, hr = int(parts[0]), int(parts[1]), int(parts[2])
        if year is not None and y != year:
            bad += 1
            continue
        if not (1 <= doy <= 366 and 0 <= hr <= 23):
            bad += 1
            continue
        vals = np.array([float(v) for v in parts[PROTON_WORDS]])
        vals[vals >= FILL - 0.005] = np.nan     # each word has its own fill value
        times.append(datetime(y, 1, 1) + timedelta(days=doy - 1, hours=hr))
        rows.append(vals)
    if not rows or bad > 0.01 * len(lines):
        raise OmniFormatError(
            f"OMNI2 parse failed: {bad} of {len(lines)} lines did not have {N_WORDS} fields. "
            f"Check the format at {config.OMNI2_FORMAT_URL}")
    return np.array(times, dtype="datetime64[s]"), np.vstack(rows)


def _compact_path(year):
    return config.CACHE_DIR / "omni" / f"omni2_{year}_protons.npz"


def load_year(year):
    """Proton channels for one year, from the compact cache or SPDF."""
    compact = _compact_path(year)
    if compact.exists():
        z = np.load(compact)
        return z["times"].astype("datetime64[s]"), z["flux"], {"source": "cache", "stale": False}
    raw_path = config.CACHE_DIR / "omni" / f"omni2_{year}.dat"
    data, meta = fetch_bytes(config.OMNI2_URL.format(year=year), raw_path)
    times, flux = parse_omni2(data.decode("ascii", errors="replace"), year)
    compact.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(compact, times=times.astype("int64"), flux=flux)
    try:
        Path(raw_path).unlink()      # the compact copy is all we need (keeps cache small)
    except OSError:
        pass
    return times, flux, meta


def load_window(start, end, lead_in_h=168):
    """OMNI proton series from (start - lead_in) to end. Lead-in feeds the causal background."""
    t0 = np.datetime64(start) - np.timedelta64(lead_in_h, "h")
    t1 = np.datetime64(end)
    years = range(int(str(t0)[:4]), int(str(t1)[:4]) + 1)
    all_t, all_f = [], []
    for y in years:
        t, f, _ = load_year(y)
        all_t.append(t)
        all_f.append(f)
    times = np.concatenate(all_t)
    flux = np.vstack(all_f)
    m = (times >= t0) & (times <= t1)
    if not m.any():
        raise OmniFormatError(f"no OMNI2 rows between {t0} and {t1}")
    series = FluxSeries(times[m], list(OMNI_ENERGIES), flux[m],
                        source="NASA SPDF OMNI2 hourly (GOES/IMP proton fluxes)")
    if np.isnan(series.channel(10.0)).mean() > 0.5:
        series.notes.append("More than half of the >10 MeV values are missing in this window.")
    return series
