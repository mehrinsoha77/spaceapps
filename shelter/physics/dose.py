"""Shielded point dose from an isotropic proton spectrum.

For a point behind a shield, each direction on the sky has its own aluminium-
equivalent thickness. We describe a location by a *shielding distribution*: a
list of (thickness g/cm^2 Al, solid-angle fraction). The target sits under an
extra layer of tissue (water) that represents body self-shielding:
skin 0.007, eye lens 0.3, blood-forming organs (BFO) 5 g/cm^2 (NASA convention).

For each energy E on the grid we slow the proton through the Al thickness and
then through the tissue depth (CSDA), and score the stopping power in water at
the residual energy. For isotropic intensity j(E) [per sr], the omnidirectional
fluence rate is 4*pi*j(E), so

    D_dot [Gy/s] = 4*pi * 1.602e-10 * sum_i f_i * Int j(E) * S_w(E_res,i(E)) dE

Dose equivalent uses the ICRP-60 quality factor Q(L) of the residual proton.

What is NOT modelled (and is stated in the UI): secondary neutrons and nuclear
fragments, 3D geometry beyond the thickness distribution, and heavy ions. GCR
is added as a separate constant measured by MSL/RAD, not computed here.
"""

from dataclasses import dataclass, field

import numpy as np

from . import stopping
from .spectrum import differential_flux

MEV_CM2_PER_G_TO_GY = 1.602176634e-10   # (1/cm^2) * (MeV cm^2/g) -> Gy
SECONDS_PER_HOUR = 3600.0

TARGET_DEPTHS = {
    # g/cm^2 of tissue (water). NASA-STD-3001 / NCRP convention.
    "skin": 0.007,
    "eye": 0.3,
    "bfo": 5.0,
}


@dataclass
class Location:
    key: str
    name: str
    shielding: list            # [(thickness g/cm^2 Al, fraction), ...]
    source: str = ""
    editable: bool = True

    def mean_thickness(self):
        return sum(t * f for t, f in self.shielding)


LOCATIONS = {
    "eva": Location(
        "eva", "EVA suit (deep space)", [(0.3, 1.0)],
        "Team assumption: ~0.3 g/cm^2 Al-equivalent suit, isotropic exposure "
        "(no credit for the vehicle blocking part of the sky; conservative)."),
    "msl_cruise": Location(
        "msl_cruise", "MSL cruise stage (RAD position)", [(3.0, 0.30), (9.0, 0.50), (50.0, 0.20)],
        "Guo et al. 2015, A&A 577 A58: ~30% of RAD's view <5 g/cm^2, 50% at 8-10, "
        "20% >=20; mean ~16 g/cm^2. Used for the RAD benchmark."),
    "cabin": Location(
        "cabin", "Crew cabin", [(5.0, 0.3), (10.0, 0.5), (20.0, 0.2)],
        "Team assumption for a lightly shielded crew cabin (mean ~10.5 g/cm^2)."),
    "shelter": Location(
        "shelter", "Storm shelter", [(20.0, 0.3), (30.0, 0.5), (50.0, 0.2)],
        "Team assumption: shelter built around stowage/water, mean ~31 g/cm^2."),
}


def _trapz_weights(x):
    w = np.zeros_like(x)
    dx = np.diff(x)
    w[:-1] += 0.5 * dx
    w[1:] += 0.5 * dx
    w[0] += x[0]          # protons that stop with < E_MIN left (Bragg region)
    return w


_WEIGHTS = _trapz_weights(stopping.GRID)
_KERNEL_CACHE = {}


def _kernel_one(thickness_al, depth_water, quality):
    """Kernel for one shield thickness, built by integrating over the residual
    energy E2 at the target instead of the incident energy E0.

    CSDA gives dE0/S_Al(E0) = dE1/S_Al(E1) and dE1/S_w(E1) = dE2/S_w(E2), so
        S_w(E2) dE0 = S_Al(E0) * S_w(E1) / S_Al(E1) dE2,
    which is smooth in E2. Integrating over E0 directly under-samples the Bragg
    peak, where protons only just reach the target.
    """
    g = stopping.GRID
    e2 = g
    e1 = stopping.energy_from_range(stopping.csda_range(e2, "water") + depth_water, "water")
    if thickness_al > 0:
        e0 = stopping.energy_from_range(stopping.csda_range(e1, "aluminum") + thickness_al, "aluminum")
        jac = (stopping.mass_stopping_power(e0, "aluminum")
               / stopping.mass_stopping_power(e1, "aluminum")
               * stopping.mass_stopping_power(e1, "water"))
    else:
        e0 = e1
        jac = stopping.mass_stopping_power(e1, "water")
    factor = jac * _WEIGHTS
    if quality:
        factor = factor * stopping.icrp60_quality_factor(0.1 * stopping.mass_stopping_power(e2, "water"))
    keep = e0 < g[-1]
    # spread each node onto the incident-energy grid by linear interpolation of j
    k = np.clip(np.searchsorted(g, e0[keep]) - 1, 0, g.size - 2)
    a = (e0[keep] - g[k]) / (g[k + 1] - g[k])
    w = np.zeros_like(g)
    np.add.at(w, k, factor[keep] * (1 - a))
    np.add.at(w, k + 1, factor[keep] * a)
    return w


def dose_kernel(shielding, target, quality):
    """Vector W such that dose rate [mGy/h or mSv/h] = j(E) @ W."""
    key = (tuple(tuple(x) for x in shielding), target, bool(quality))
    if key not in _KERNEL_CACHE:
        depth = TARGET_DEPTHS[target]
        resp = sum(f * _kernel_one(t, depth, quality) for t, f in shielding)
        _KERNEL_CACHE[key] = (4 * np.pi * MEV_CM2_PER_G_TO_GY * SECONDS_PER_HOUR * 1e3) * resp
    return _KERNEL_CACHE[key]


@dataclass
class DoseSeries:
    """Dose-equivalent rates (mSv/h) and dose rates (mGy/h) per target."""
    rate_msv_h: dict = field(default_factory=dict)     # target -> (T,)
    rate_mgy_h: dict = field(default_factory=dict)


def dose_rates(energies, integral_flux, shielding, steepening=0.0, targets=("skin", "eye", "bfo")):
    """SEP dose rates for a time series of integral channels at one location."""
    diff = differential_flux(energies, integral_flux, stopping.GRID, steepening)
    out = DoseSeries()
    for t in targets:
        out.rate_msv_h[t] = diff @ dose_kernel(shielding, t, True)
        out.rate_mgy_h[t] = diff @ dose_kernel(shielding, t, False)
    return out


def integrate(rate_per_h, hours):
    """Integrate a rate sampled at times `hours` (trapezoid), NaN treated as 0."""
    r = np.nan_to_num(np.asarray(rate_per_h, dtype=float))
    h = np.asarray(hours, dtype=float)
    if r.size < 2:
        return 0.0
    return float(np.sum(0.5 * (r[1:] + r[:-1]) * np.diff(h)))


# Dose uses channels >= 10 MeV only (see data.series.dose_channels). That is valid
# only if every location stops 10 MeV protons; check it at import time.
_MIN_T = min(t for loc in LOCATIONS.values() for t, _ in loc.shielding)
assert _MIN_T >= float(stopping.csda_range(10.0, "aluminum")), \
    "a location is thinner than the 10 MeV proton range; include lower channels in dose"

