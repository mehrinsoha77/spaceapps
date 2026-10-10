"""Proton stopping power and CSDA range in water and aluminum.

Method: the Bethe formula for protons (no shell or density-effect corrections),
integrated numerically to get the continuous-slowing-down (CSDA) range.

Why this is good enough here: between ~1 MeV and ~1 GeV the uncorrected Bethe
formula agrees with NIST PSTAR to within a few percent for water and aluminum.
tests/test_physics.py checks this against published PSTAR values.

Units:
    energy             MeV (kinetic)
    mass stopping power MeV cm^2 / g
    range / thickness  g / cm^2   (areal density)
"""

import numpy as np

ME_C2 = 0.51099895      # electron rest energy, MeV
MP_C2 = 938.272088      # proton rest energy, MeV
K_BETHE = 0.307075      # 4 pi N_A r_e^2 m_e c^2, MeV cm^2 / mol

MATERIALS = {
    # Z/A and mean excitation energy I, the same values NIST PSTAR uses
    "water": {"z_over_a": 0.555087, "i_ev": 75.0},
    "aluminum": {"z_over_a": 13.0 / 26.9815385, "i_ev": 166.0},
}

# Energy grid used everywhere in SHELTER (log spaced)
E_MIN = 0.5
E_MAX = 3000.0
GRID = np.geomspace(E_MIN, E_MAX, 700)


def mass_stopping_power(energy, material):
    """Bethe mass stopping power (MeV cm^2/g) for protons of kinetic energy `energy` (MeV)."""
    mat = MATERIALS[material]
    e = np.asarray(energy, dtype=float)
    gamma = 1.0 + e / MP_C2
    beta2 = 1.0 - 1.0 / (gamma * gamma)
    bg2 = beta2 * gamma * gamma
    ratio = ME_C2 / MP_C2
    t_max = 2.0 * ME_C2 * bg2 / (1.0 + 2.0 * gamma * ratio + ratio * ratio)
    i_mev = mat["i_ev"] * 1e-6
    log_term = 0.5 * np.log(2.0 * ME_C2 * bg2 * t_max / (i_mev * i_mev))
    return K_BETHE * mat["z_over_a"] / beta2 * (log_term - beta2)


def _build_range_table(material):
    s = mass_stopping_power(GRID, material)
    # Range below the grid start: approximate R(E) ~ E / S(E) * 0.6
    # (it is a few micrograms/cm^2 and never matters for shielding here)
    r0 = 0.6 * GRID[0] / s[0]
    inv = 1.0 / s
    steps = 0.5 * (inv[1:] + inv[:-1]) * np.diff(GRID)
    return np.concatenate([[r0], r0 + np.cumsum(steps)])


RANGE_TABLE = {name: _build_range_table(name) for name in MATERIALS}
STOPPING_TABLE = {name: mass_stopping_power(GRID, name) for name in MATERIALS}


def csda_range(energy, material):
    """CSDA range (g/cm^2) for protons of the given energy (MeV); 0 for E <= 0."""
    e = np.asarray(energy, dtype=float)
    out = np.zeros_like(e)
    pos = e > 0
    out[pos] = np.exp(np.interp(np.log(e[pos]), np.log(GRID), np.log(RANGE_TABLE[material]),
                                left=-np.inf))
    low = pos & (e < GRID[0])
    out[low] = RANGE_TABLE[material][0] * (e[low] / GRID[0]) ** 1.7
    return out


def energy_from_range(rng, material):
    """Inverse of csda_range. Returns 0 where the range is <= 0 (proton stopped)."""
    rng = np.asarray(rng, dtype=float)
    out = np.zeros_like(rng)
    ok = rng > RANGE_TABLE[material][0]
    out[ok] = np.exp(np.interp(np.log(rng[ok]), np.log(RANGE_TABLE[material]), np.log(GRID)))
    # Very short ranges below the table: tiny energies, treat as stopped-ish but nonzero
    tiny = (rng > 0) & ~ok
    out[tiny] = GRID[0] * (rng[tiny] / RANGE_TABLE[material][0]) ** (1 / 1.7)
    return out


def residual_energy(energy, thickness, material):
    """Kinetic energy left after crossing `thickness` g/cm^2 of `material` (0 if stopped)."""
    if thickness <= 0:
        return np.asarray(energy, dtype=float).copy()
    return energy_from_range(csda_range(energy, material) - thickness, material)


def let_kev_per_um(energy):
    """Unrestricted LET in water (keV/um) for protons: 0.1 * S (MeV cm^2/g) at density 1."""
    return 0.1 * mass_stopping_power(np.maximum(energy, E_MIN), "water")


def icrp60_quality_factor(let):
    """ICRP Publication 60 Q(L), L in keV/um of water."""
    let = np.asarray(let, dtype=float)
    q = np.ones_like(let)
    mid = (let >= 10) & (let <= 100)
    q[mid] = 0.32 * let[mid] - 2.2
    hi = let > 100
    q[hi] = 300.0 / np.sqrt(let[hi])
    return q
