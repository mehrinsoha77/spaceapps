"""Catalog of historical solar particle events used for replay and validation.

Windows start about a day before onset so the replay begins in quiet conditions.
All flux data come from NASA SPDF OMNI2 (hourly); markers come from NASA DONKI
(DONKI coverage begins in 2010, so older events have no markers).
"""

import json

import numpy as np

from .. import config
from . import donki, omni
from .http import DataUnavailable
from .synthetic import make_synthetic

EVENTS = [
    {"id": "1989-10", "title": "October 1989 (NASA design-reference SPE)", "start": "1989-10-18", "end": "1989-10-31",
     "why": "NASA-STD-3001 sizes storm shelters against an event of this class."},
    {"id": "2000-07", "title": "Bastille Day 2000", "start": "2000-07-13", "end": "2000-07-19",
     "why": "Fast, hard-spectrum event (GLE 59)."},
    {"id": "2001-11", "title": "November 2001", "start": "2001-11-03", "end": "2001-11-10",
     "why": "One of the largest >10 MeV peaks of cycle 23."},
    {"id": "2003-10", "title": "Halloween storms 2003", "start": "2003-10-26", "end": "2003-11-06",
     "why": "Three large events back-to-back: tests repeated alerts."},
    {"id": "2005-01", "title": "January 2005 (GLE 69)", "start": "2005-01-15", "end": "2005-01-25",
     "why": "Very hard spectrum: hardest case for thick shielding."},
    {"id": "2012-01", "title": "January 2012 (MSL/RAD benchmark)", "start": "2012-01-22", "end": "2012-01-31",
     "why": "Measured inside MSL during its cruise to Mars.", "rad_msv": 4.0,
     "rad_window": ["2012-01-23", "2012-01-30"]},
    {"id": "2012-03", "title": "March 2012 (MSL/RAD benchmark)", "start": "2012-03-06", "end": "2012-03-16",
     "why": "Measured inside MSL during its cruise to Mars.", "rad_msv": 19.5,
     "rad_window": ["2012-03-07", "2012-03-16"]},
    {"id": "2012-05", "title": "May 2012 (MSL/RAD benchmark, GLE 71)", "start": "2012-05-16", "end": "2012-05-21",
     "why": "Measured inside MSL during its cruise to Mars.", "rad_msv": 1.2,
     "rad_window": ["2012-05-17", "2012-05-21"]},
    {"id": "2017-09", "title": "September 2017 (GLE 72)", "start": "2017-09-04", "end": "2017-09-16",
     "why": "Most recent large event of cycle 24."},
    {"id": "synthetic", "title": "SYNTHETIC self-test (not real data)", "start": "2030-01-01", "end": "2030-01-09",
     "why": "Software self-test only.", "synthetic": True},
]

RAD_SOURCE = ("Guo et al. 2015, A&A 577, A58: SEP dose equivalent measured by MSL/RAD during cruise - "
              "23-29 Jan 2012: 4.0 mSv (two events); 7-15 Mar 2012: 19.5 mSv (two events); "
              "17 May 2012: 1.2 mSv.")


def get_event(event_id):
    for e in EVENTS:
        if e["id"] == event_id:
            return e
    raise KeyError(event_id)


def _event_cache(event_id):
    return config.CACHE_DIR / "events" / event_id


def load_event(event_id, with_markers=True):
    """Return (FluxSeries incl. 168 h lead-in, markers, status)."""
    ev = get_event(event_id)
    if ev.get("synthetic"):
        return make_synthetic(), [], {"flux": "synthetic", "markers": "none"}
    series = omni.load_window(ev["start"] + "T00:00:00", ev["end"] + "T23:00:00")
    markers, status = [], {"flux": series.source}
    if with_markers:
        if int(ev["start"][:4]) >= 2010:
            markers, mstatus = donki.load_markers(ev["start"], ev["end"], _event_cache(event_id))
            status["markers"] = mstatus
        else:
            status["markers"] = "DONKI starts in 2010; no markers for this event"
    return series, markers, status


def availability():
    """Which events can be replayed right now without a download (bundled or cached).
    `loadable` is also true for events that can still be downloaded (not offline)."""
    out = []
    for ev in EVENTS:
        if ev.get("synthetic"):
            ok = True
        else:
            first = np.datetime64(ev["start"] + "T00:00:00") - np.timedelta64(168, "h")
            years = range(int(str(first)[:4]), int(ev["end"][:4]) + 1)
            dirs = (config.BUNDLED_DIR / "omni", config.CACHE_DIR / "omni")
            ok = all(any((d / f"omni2_{y}_protons.npz").exists() or (d / f"omni2_{y}.dat").exists()
                         for d in dirs) for y in years)
        out.append({**ev, "cached": ok, "loadable": ok or not config.OFFLINE})
    return out


def prefetch(event_ids=None, log=print):
    """Download and cache everything the demo needs. Run this before going offline."""
    results = {}
    for ev in EVENTS:
        if ev.get("synthetic") or (event_ids and ev["id"] not in event_ids):
            continue
        try:
            series, markers, status = load_event(ev["id"])
            peak = np.nanmax(series.channel(10.0))
            results[ev["id"]] = {"ok": True, "hours": int(series.times.size), "peak_10mev_pfu": float(peak),
                                 "markers": len(markers), "status": status}
            log(f"[ok]   {ev['id']}: {series.times.size} hourly rows, peak >10 MeV = {peak:,.0f} pfu, "
                f"{len(markers)} DONKI markers")
        except (DataUnavailable, omni.OmniFormatError, OSError) as exc:
            results[ev["id"]] = {"ok": False, "error": str(exc)}
            log(f"[FAIL] {ev['id']}: {exc}")
    (config.CACHE_DIR).mkdir(parents=True, exist_ok=True)
    (config.CACHE_DIR / "prefetch_report.json").write_text(json.dumps(results, indent=2, default=str))
    return results
