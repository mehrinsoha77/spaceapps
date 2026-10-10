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


def fill_short_gaps(flux, max_gap=3):
    """Log-linear interpolation across gaps of <= max_gap samples, per channel."""
    out = flux.copy()
    n = out.shape[0]
    for c in range(out.shape[1]):
        col = out[:, c]
        bad = np.isnan(col) | (col <= 0)
        if not bad.any() or bad.all():
            continue
        idx = np.arange(n)
        good = ~bad
        interp = np.exp(np.interp(idx, idx[good], np.log(col[good])))
        # only fill runs that are short and bounded on both sides
        run_start = None
        for i in range(n + 1):
            is_bad = i < n and bad[i]
            if is_bad and run_start is None:
                run_start = i
            elif not is_bad and run_start is not None:
                if run_start > 0 and i < n and (i - run_start) <= max_gap:
                    col[run_start:i] = interp[run_start:i]
                run_start = None
        out[:, c] = col
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


def sep_flux(series, noise_gate_pfu=0.1, ref_energy=10.0):
    """Background-subtracted SEP flux (T, C). Rows where the >=ref_energy channel is
    below the noise gate are set to zero; rows with missing data stay NaN."""
    raw = fill_short_gaps(series.flux)
    bg = causal_background(raw, series.hours)
    sep = np.where(np.isnan(raw), np.nan, np.maximum(raw - np.nan_to_num(bg), 0.0))
    ref = series.energies.index(ref_energy) if ref_energy in series.energies else 0
    quiet = (sep[:, ref] < noise_gate_pfu) & ~np.isnan(sep[:, ref])
    sep[quiet] = np.where(np.isnan(sep[quiet]), np.nan, 0.0)
    return sep, bg
