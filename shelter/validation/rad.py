"""Benchmark against MSL/RAD: dose measured inside a spacecraft flying to Mars.

Measured SEP dose equivalent during MSL cruise (Guo et al. 2015, A&A 577 A58):
    23-29 Jan 2012: 4.0 mSv    7-15 Mar 2012: 19.5 mSv    17 May 2012: 1.2 mSv

SHELTER estimate: OMNI2 (GOES at Earth) proton channels -> causal background
removal -> dose equivalent at a near-surface point (0.007 g/cm^2 water) behind
the MSL cruise shielding distribution from the same paper.

Known mismatches, reported with the result:
  * GOES is at Earth; MSL was up to ~1 AU away and magnetically connected
    to a different part of the Sun. Per-event errors of 2-3x are expected.
  * RAD's view is a cone, not 4 pi; the shielding distribution describes it.
  * No secondaries in SHELTER's transport.
Leave-one-out calibration: fit one scale factor on two events, test on the third.
"""

import numpy as np

from ..data.events import EVENTS, RAD_SOURCE, load_event
from ..data.series import dose_channels, sep_flux
from ..physics import dose as dose_mod
from ..physics.dose import LOCATIONS


def estimate_event(ev, target="skin"):
    series, _, status = load_event(ev["id"], with_markers=False)
    sep, _ = sep_flux(series)
    w0, w1 = (np.datetime64(ev["rad_window"][0] + "T00:00:00"), np.datetime64(ev["rad_window"][1] + "T00:00:00"))
    m = (series.times >= w0) & (series.times <= w1)
    hours = series.hours[m]
    res = {}
    for bound, steep in (("hard", 0.0), ("soft", 1.0)):
        d_e, d_sep = dose_channels(series.energies, sep[m])
        ds = dose_mod.dose_rates(d_e, d_sep, LOCATIONS["msl_cruise"].shielding,
                                 steepening=steep, targets=(target,))
        res[bound] = dose_mod.integrate(ds.rate_msv_h[target], hours)
    missing = float(np.isnan(dose_channels(series.energies, sep[m])[1]).any(axis=1).mean())
    return {"id": ev["id"], "title": ev["title"], "measured_msv": ev["rad_msv"],
            "predicted_hard_msv": res["hard"], "predicted_soft_msv": res["soft"],
            "predicted_min_msv": min(res.values()), "predicted_max_msv": max(res.values()),
            "missing_fraction": missing, "flux_source": status["flux"]}


def run_benchmark():
    rows = [estimate_event(ev) for ev in EVENTS if "rad_msv" in ev]
    for r in rows:
        mid = np.sqrt(max(r["predicted_hard_msv"], 1e-12) * max(r["predicted_soft_msv"], 1e-12))
        r["predicted_mid_msv"] = mid
        r["ratio_mid"] = mid / r["measured_msv"]
    # leave-one-out calibration on the geometric-mid estimate
    for k, r in enumerate(rows):
        others = [o for j, o in enumerate(rows) if j != k and o["predicted_mid_msv"] > 0]
        if others:
            c = float(np.exp(np.mean([np.log(o["measured_msv"] / o["predicted_mid_msv"]) for o in others])))
            r["loo_factor"] = c
            r["loo_prediction_msv"] = c * r["predicted_mid_msv"]
            r["loo_ratio"] = r["loo_prediction_msv"] / r["measured_msv"]
    total_meas = sum(r["measured_msv"] for r in rows)
    total_pred = sum(r["predicted_mid_msv"] for r in rows)
    logs = [abs(np.log(r["ratio_mid"])) for r in rows if r["ratio_mid"] > 0]
    return {
        "rows": rows,
        "total_measured_msv": total_meas,
        "total_predicted_mid_msv": total_pred,
        "mean_abs_log_error": float(np.mean(logs)) if logs else None,
        "typical_factor_error": float(np.exp(np.mean(logs))) if logs else None,
        "source": RAD_SOURCE,
        "method": "OMNI2 GOES protons, causal background removal, piecewise power-law spectrum "
                  "(hard: last slope continues above the top channel; soft: index +1 above it; the range is shown), "
                  "CSDA transport through MSL cruise shielding distribution, ICRP-60 Q(L).",
        "caveats": [
            "GOES measures at Earth; MSL was elsewhere in the inner heliosphere (different magnetic connection).",
            "Only three benchmark periods: treat the calibration factor as indicative, not definitive.",
            "Secondary particles are not transported; they are absorbed into the calibration factor.",
        ],
    }
