"""A clearly labelled SYNTHETIC event for software self-tests and offline UI checks.

It is NOT real data and the UI shows a red banner whenever it is used.
Shape: two injections with a fast rise and exponential decay, and a spectral
index that softens with time, written in OMNI's channel layout.
"""

import numpy as np

from .omni import OMNI_ENERGIES
from .series import FluxSeries


def make_synthetic(hours=192, start="2030-01-01T00:00:00"):
    t = np.arange(hours + 168)            # 168 h lead-in for the causal background
    times = np.datetime64(start) - np.timedelta64(168, "h") + t.astype("timedelta64[h]")
    h = t - 168.0
    bg = np.array([2.0, 1.0, 0.6, 0.35, 0.25, 0.2])        # quiet-time pfu per channel
    flux = np.tile(bg, (t.size, 1)).astype(float)

    def injection(onset, rise, decay, peak10, gamma0):
        tt = h - onset
        prof = np.where(tt < 0, 0.0, (1 - np.exp(-np.maximum(tt, 0) / rise)) * np.exp(-np.maximum(tt, 0) / decay))
        prof = prof / prof.max()
        gamma = gamma0 + 0.01 * np.maximum(tt, 0)          # softens over time
        e = np.array(OMNI_ENERGIES)
        return peak10 * prof[:, None] * (e[None, :] / 10.0) ** (-gamma[:, None])

    flux += injection(onset=24, rise=4, decay=22, peak10=3000.0, gamma0=1.6)
    flux += injection(onset=110, rise=3, decay=15, peak10=400.0, gamma0=2.2)
    rng = np.random.default_rng(7)
    flux *= np.exp(rng.normal(0, 0.04, flux.shape))
    s = FluxSeries(times.astype("datetime64[s]"), list(OMNI_ENERGIES), flux,
                   source="SYNTHETIC self-test profile (not real data)", synthetic=True)
    s.notes.append("SYNTHETIC DATA - for software testing only. Do not present as a real event.")
    return s
