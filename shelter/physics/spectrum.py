"""Turn GOES-style integral proton channels J(>E) into a differential spectrum j(E).

GOES reports integral flux J(>E) in "pfu" = protons / (cm^2 s sr) for a few
thresholds (e.g. >10, >30, >60 MeV in OMNI; >1 ... >500 MeV in SWPC live data).

Model: piecewise power law in log-log space between channels,
    J(>E) = J_k * (E / E_k) ** (-gamma_k)            for E_k <= E < E_{k+1}
so the differential flux is
    j(E) = -dJ/dE = gamma_k * J(>E) / E.
Below the lowest channel the first segment is extended; above the highest
channel the last segment's index is extended, optionally steepened by
`steepening` (SEP spectra usually roll over at high energy, so steepening = 0
is the conservative / higher-dose choice). The UI shows both bounds.
"""

import numpy as np

FLOOR = 1e-6          # pfu, keeps logs finite
MIN_INDEX = 0.3       # flattest allowed segment index


def differential_flux(energies, integral_flux, grid, steepening=0.0):
    """Vectorised j(E) on `grid`.

    energies:       (C,) channel thresholds in MeV, ascending
    integral_flux:  (T, C) J(>E) in pfu (background subtracted, >= 0, may contain NaN)
    grid:           (G,) energies in MeV
    returns:        (T, G) differential flux, protons/(cm^2 s sr MeV); rows with any
                    NaN channel return NaN; rows with no flux return 0.
    """
    e = np.asarray(energies, dtype=float)
    j_int = np.atleast_2d(np.asarray(integral_flux, dtype=float))
    n_t, n_c = j_int.shape
    if n_c < 2:
        raise ValueError("need at least two integral channels")
    out = np.zeros((n_t, grid.size))

    bad = np.isnan(j_int).any(axis=1)
    zero = (np.nan_to_num(j_int[:, 0]) <= 0) & ~bad
    rows = ~bad & ~zero
    if rows.any():
        j = np.maximum(j_int[rows], FLOOR)
        # enforce non-increasing J with energy
        j = np.minimum.accumulate(j, axis=1)
        log_e = np.log(e)
        gam = -np.diff(np.log(j), axis=1) / np.diff(log_e)          # (R, C-1)
        gam = np.maximum(gam, MIN_INDEX)
        # rebuild channel values consistent with clamped indices
        log_j = np.empty_like(j)
        log_j[:, 0] = np.log(j[:, 0])
        log_j[:, 1:] = log_j[:, :1] - np.cumsum(gam * np.diff(log_e), axis=1)

        log_g = np.log(grid)
        seg = np.clip(np.searchsorted(e, grid, side="right") - 1, 0, n_c - 2)  # (G,)
        above = grid >= e[-1]
        anchor = np.where(above, n_c - 1, seg)
        g_idx = gam[:, seg]                                           # (R, G)
        g_idx = np.where(above[None, :], g_idx + steepening, g_idx)
        log_jg = log_j[:, anchor] - g_idx * (log_g[None, :] - log_e[anchor][None, :])
        out[rows] = g_idx * np.exp(log_jg) / grid[None, :]
    out[bad] = np.nan
    return out


def integral_from_differential(grid, diff, threshold):
    """Numerically integrate j(E) above `threshold` (used by tests)."""
    m = grid >= threshold
    g = grid[m]
    d = diff[..., m]
    return np.sum(0.5 * (d[..., 1:] + d[..., :-1]) * np.diff(g), axis=-1)
