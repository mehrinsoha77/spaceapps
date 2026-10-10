"""Proton flux time series plus the causal (no-look-ahead) background removal."""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class FluxSeries:
    times: np.ndarray            # datetime64[s], ascending
    energies: list               # channel thresholds, MeV, ascending
    flux: np.ndarray             # (T, C) integral flux J(>E), pfu, raw (NaN = missing)
    source: str
    synthetic: bool = False
    notes: list = field(default_factory=list)

    @property
    def hours(self):
        return (self.times - self.times[0]).astype("timedelta64[s]").astype(float) / 3600.0

    def iso_times(self):
        return [str(t) + "Z" for t in self.times.astype("datetime64[s]")]

    def channel(self, energy):
        return self.flux[:, self.energies.index(energy)]

    def slice(self, start, end):
        m = (self.times >= np.datetime64(start)) & (self.times <= np.datetime64(end))
        return FluxSeries(self.times[m], list(self.energies), self.flux[m], self.source,
                          self.synthetic, list(self.notes))


NOISE_GATE_PFU = 0.1


def fill_short_gaps(flux, max_gap=3):
    """Carry the last good value forward over the first `max_gap` samples of a gap, per channel.

    Causal on purpose: a filled value depends only on earlier samples, and whether a
    sample is filled does not depend on how long the gap turns out to be (unknown at
    that time). Interpolating to the far side of the gap would use future data.
    """
    out = np.array(flux, dtype=float, copy=True)
    for c in range(out.shape[1]):
        col = out[:, c]
        last, since = np.nan, 0
        for i in range(col.size):
            if np.isfinite(col[i]) and col[i] > 0:
                last, since = col[i], 0
                continue
            since += 1
            if np.isfinite(last) and since <= max_gap:
                col[i] = last
    return out


def causal_background(flux, hours, window_h=168.0, pct=10.0):
    """Per-channel background at each time = pct-th percentile of the raw flux over
    the trailing `window_h` hours, using ONLY samples at or before that time."""
    bg = np.full_like(flux, np.nan)
    start = 0
    for i in range(flux.shape[0]):
        while hours[i] - hours[start] > window_h:
            start += 1
        win = flux[start:i + 1]
        with np.errstate(all="ignore"):
            bg[i] = np.nanpercentile(win, pct, axis=0) if np.isfinite(win).any() else np.nan
    return bg


DOSE_MIN_ENERGY = 10.0


def dose_channels(energies, sep, min_e=DOSE_MIN_ENERGY):
    """Channels used for dose: >= 10 MeV only.

    Every SHELTER location has >= 0.3 g/cm^2 Al, which stops protons below ~14 MeV
    (CSDA range of 10 MeV protons in Al is 0.17 g/cm^2), so lower channels add no
    dose -- but a missing low channel would otherwise blank the whole hour.
    """
    idx = [k for k, e in enumerate(energies) if e >= min_e]
    return [energies[k] for k in idx], sep[:, idx]


def sep_flux(series, noise_gate_pfu=NOISE_GATE_PFU, ref_energy=10.0):
    """Background-subtracted SEP flux (T, C). Rows where the >=ref_energy channel is
    below the noise gate are set to zero; rows with missing data stay NaN."""
    raw = fill_short_gaps(series.flux)      # causal: never fills from the far side of a gap
    bg = causal_background(raw, series.hours)
    sep = np.where(np.isnan(raw), np.nan, np.maximum(raw - np.nan_to_num(bg), 0.0))
    ref = series.energies.index(ref_energy) if ref_energy in series.energies else 0
    quiet = (sep[:, ref] < noise_gate_pfu) & ~np.isnan(sep[:, ref])
    sep[quiet] = np.where(np.isnan(sep[quiet]), np.nan, 0.0)
    return sep, bg
