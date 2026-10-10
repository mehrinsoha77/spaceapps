"""NASA SPDF OMNI2 hourly data: proton fluxes >1, >2, >4, >10, >30, >60 MeV.

Format (from omni2.text, the official format description): 55 whitespace-
separated words per hour. Word 1 = year, 2 = day of year, 3 = hour,
words 43-48 = proton flux (1/(cm^2 s sr)) above 1, 2, 4, 10, 30, 60 MeV.
Fill values: 999999.99 (word 43) and 99999.99 (words 44-48).

Lines are fixed-width (FORTRAN format in omni2.text). A value that fills its whole
field touches the previous one (e.g. >1 MeV >= 1e6 pfu at a storm peak), so
whitespace splitting fails exactly at the hours that matter most. Such lines are
read by column instead, once the file's own well-formed lines confirm the layout.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .. import config
from .http import bundled_path, fetch_bytes
from .series import FluxSeries

OMNI_ENERGIES = [1.0, 2.0, 4.0, 10.0, 30.0, 60.0]
N_WORDS = 55
PROTON_WORDS = slice(42, 48)   # 0-based slice of words 43..48
# Fill values per word (omni2.text): F10.2 for >1 MeV, F9.2 for the rest.
FILL = np.array([999999.99, 99999.99, 99999.99, 99999.99, 99999.99, 99999.99])
OMNI2_FORMAT = ("2I4,I3,I5,2I3,2I4,14F6.1,F9.0,F6.1,F6.0,2F6.1,F6.3,F6.2,F9.0,F6.1,F6.0,"
                "2F6.1,F6.3,2F7.2,F6.1,I3,I4,I6,I5,F10.2,5F9.2,I3,I4,F6.1,F6.1,2I6,F5.1")


def _column_bounds(fmt):
    bounds, pos = [], 0
    for item in fmt.split(","):
        rep, _, width = re.fullmatch(r"(\d*)([IF])(\d+)(?:\.\d+)?", item).groups()
        for _ in range(int(rep or 1)):
            bounds.append((pos, pos + int(width)))
            pos += int(width)
    return bounds


COLUMNS = _column_bounds(OMNI2_FORMAT)
assert len(COLUMNS) == N_WORDS


class OmniFormatError(ValueError):
    pass


def _by_columns(line):
    """Words 1-3 and 43-48 read by fixed column, or None if the line does not fit."""
    if len(line) > COLUMNS[-1][1]:
        return None
    try:
        head = [int(line[a:b]) for a, b in COLUMNS[:3]]
        vals = [float(line[a:b]) for a, b in COLUMNS[PROTON_WORDS]]
    except ValueError:
        return None
    return head, vals


def _by_words(parts):
    return [int(v) for v in parts[:3]], [float(v) for v in parts[PROTON_WORDS]]


def parse_omni2(text, year=None):
    """Parse an OMNI2 yearly file. Returns (times datetime64[s], flux (T,6))."""
    times, rows, bad = [], [], 0
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    # Trust the column layout only if it reproduces the first well-formed line.
    first = next((ln for ln in lines if len(ln.split()) == N_WORDS), None)
    columns_ok = first is not None and _by_columns(first) == _by_words(first.split())
    for ln in lines:
        parts = ln.split()
        parsed = _by_words(parts) if len(parts) == N_WORDS else _by_columns(ln) if columns_ok else None
        if parsed is None:
            bad += 1
            continue
        (y, doy, hr), vals = parsed
        if year is not None and y != year:
            bad += 1
            continue
        if not (1 <= doy <= 366 and 0 <= hr <= 23):
            bad += 1
            continue
        vals = np.array(vals)
        vals[np.abs(vals - FILL) < 0.005] = np.nan   # each word has its own fill value; larger values are real
        times.append(datetime(y, 1, 1) + timedelta(days=doy - 1, hours=hr))
        rows.append(vals)
    if not rows or bad > 0.01 * len(lines):
        raise OmniFormatError(
            f"OMNI2 parse failed: {bad} of {len(lines)} lines could not be read as {N_WORDS} fields. "
            f"Check the format at {config.OMNI2_FORMAT_URL}")
    return np.array(times, dtype="datetime64[s]"), np.vstack(rows)


def _compact_path(year):
    return config.CACHE_DIR / "omni" / f"omni2_{year}_protons.npz"


def load_year(year):
    """Proton channels for one year, from the compact cache or SPDF."""
    compact = _compact_path(year)
    for path, source in ((bundled_path(compact), "bundled"), (compact, "cache")):
        if path is not None and path.exists():
            z = np.load(path)
            return z["times"].astype("datetime64[s]"), z["flux"], {"source": source, "stale": False}
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
    # Regular hourly grid: an hour missing from the file becomes a NaN row (a data gap)
    # instead of silently stretching the time step.
    grid = np.arange(t0, t1 + np.timedelta64(1, "h"), np.timedelta64(1, "h")).astype("datetime64[s]")
    full = np.full((grid.size, len(OMNI_ENERGIES)), np.nan)
    k = ((times[m] - grid[0]) // np.timedelta64(1, "h")).astype(int)
    full[k] = flux[m]
    series = FluxSeries(grid, list(OMNI_ENERGIES), full,
                        source="NASA SPDF OMNI2 hourly (GOES/IMP proton fluxes)")
    if grid.size > m.sum():
        series.notes.append(f"{grid.size - int(m.sum())} hours are missing from the OMNI2 file in this window.")
    if np.isnan(series.channel(10.0)).mean() > 0.5:
        series.notes.append("More than half of the >10 MeV values are missing in this window.")
    return series
