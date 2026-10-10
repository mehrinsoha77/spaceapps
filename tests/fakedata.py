"""TEST FIXTURES ONLY: files in the exact OMNI2 / SWPC / DONKI formats, filled
with made-up numbers so the real-data code paths can run without internet.
Nothing here is ever written to the real cache or shown as real data."""

import json
from datetime import datetime, timedelta

import numpy as np

QUIET = np.array([2.0, 1.0, 0.6, 0.35, 0.25, 0.2])
E6 = np.array([1.0, 2.0, 4.0, 10.0, 30.0, 60.0])


def _profile(hours_since_onset, peak10, gamma, rise=4.0, decay=20.0):
    tt = np.maximum(hours_since_onset, 0)
    prof = np.where(hours_since_onset < 0, 0.0, (1 - np.exp(-tt / rise)) * np.exp(-tt / decay))
    norm = (1 - np.exp(-rise * np.log(1 + decay / rise) / rise)) * np.exp(-rise * np.log(1 + decay / rise) / decay)
    return peak10 * prof / max(norm, 1e-9) * (E6 / 10.0) ** (-gamma)


def omni_year_text(year, injections, gap_hours=()):
    """injections: list of (onset datetime, peak10 pfu, gamma)."""
    lines = []
    t = datetime(year, 1, 1)
    end = datetime(year + 1, 1, 1)
    filler = ["1771", "99", "99", "999", "999", "999.9"] + ["999.9"] * 33
    while t < end:
        flux = QUIET.copy()
        for onset, peak, gam in injections:
            flux = flux + _profile((t - onset).total_seconds() / 3600.0, peak, gam)
        doy = t.timetuple().tm_yday
        prot = [f"{flux[0]:10.2f}"] + [f"{v:9.2f}" for v in flux[1:]]
        if t in gap_hours:
            prot = ["999999.99"] + ["99999.99"] * 5
        words = [f"{year:4d}", f"{doy:4d}", f"{t.hour:3d}"] + filler + prot + [" 0", "999", "999.9", "999.9", "99999", "99999", "999.9"]
        assert len(words) == 55, len(words)
        lines.append(" ".join(words))
        t += timedelta(hours=1)
    return "\n".join(lines) + "\n"


def write_fake_cache(cache_dir):
    """OMNI2 2012 with three fake storms at the RAD benchmark dates, SWPC live
    feed, and DONKI records."""
    omni = cache_dir / "omni"
    omni.mkdir(parents=True, exist_ok=True)
    inj = [(datetime(2012, 1, 23, 5), 3000.0, 2.2), (datetime(2012, 3, 7, 5), 4000.0, 1.9),
           (datetime(2012, 5, 17, 2), 200.0, 1.4)]
    (omni / "omni2_2012.dat").write_text(omni_year_text(2012, inj))
    (omni / "omni2_2011.dat").write_text(omni_year_text(2011, []))   # lead-in for January

    # SWPC live feed in the verified record format
    live = cache_dir / "live"
    live.mkdir(parents=True, exist_ok=True)
    recs = []
    t0 = datetime(2026, 10, 3, 0, 0)
    energies = [1, 5, 10, 30, 50, 60, 100, 500]
    for k in range(7 * 24 * 12):
        t = t0 + timedelta(minutes=5 * k)
        h = k / 12.0
        for e in energies:
            base = {1: 40, 5: 1.0, 10: 0.32, 30: 0.27, 50: 0.25, 60: 0.24, 100: 0.23, 500: 0.05}[e]
            bump = 0.0 if h < 150 else 60.0 * (1 - np.exp(-(h - 150) / 3)) * (e / 10.0) ** -2.0
            recs.append({"time_tag": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "satellite": 18,
                         "flux": base + bump, "energy": f">={e} MeV"})
    (live / "swpc_protons_7d.json").write_text(json.dumps(recs))

    # DONKI-shaped records for the March 2012 event
    ev = cache_dir / "events" / "2012-03"
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "donki_FLR_2012-03-06_2012-03-16.json").write_text(json.dumps([
        {"flrID": "2012-03-07T00:02:00-FLR-001", "beginTime": "2012-03-07T00:02Z",
         "peakTime": "2012-03-07T00:24Z", "classType": "X5.4"}]))
    (ev / "donki_SEP_2012-03-06_2012-03-16.json").write_text(json.dumps([
        {"sepID": "2012-03-07T05:10:00-SEP-001", "eventTime": "2012-03-07T05:10Z",
         "instruments": [{"displayName": "GOES13: SEM/EPS >10 MeV"}]}]))
    (ev / "donki_CME_2012-03-06_2012-03-16.json").write_text(json.dumps([
        {"activityID": "2012-03-07T00:24:00-CME-001", "startTime": "2012-03-07T00:24Z",
         "cmeAnalyses": [{"isMostAccurate": True, "speed": 2684.0}]}]))
    return cache_dir
