import unittest

import numpy as np

from shelter.physics import stopping
from shelter.physics.dose import dose_rates, LOCATIONS
from shelter.physics.spectrum import differential_flux, integral_from_differential


class StoppingPower(unittest.TestCase):
    # NIST PSTAR, liquid water: (MeV, total stopping power MeV cm2/g, CSDA range g/cm2)
    PSTAR_WATER = [(10, 45.67, 0.1230), (50, 12.45, 2.227), (100, 7.289, 7.718), (200, 4.492, 25.96)]

    def test_water_matches_pstar(self):
        for e, s_ref, r_ref in self.PSTAR_WATER:
            s = float(stopping.mass_stopping_power(e, "water"))
            r = float(stopping.csda_range(e, "water"))
            self.assertAlmostEqual(s / s_ref, 1.0, delta=0.02, msg=f"S at {e} MeV")
            self.assertAlmostEqual(r / r_ref, 1.0, delta=0.02, msg=f"range at {e} MeV")

    def test_aluminium_100mev_range(self):
        # PSTAR aluminium CSDA range at 100 MeV is about 9.98 g/cm2
        self.assertAlmostEqual(float(stopping.csda_range(100.0, "aluminum")) / 9.98, 1.0, delta=0.03)

    def test_range_inverse_and_stopping(self):
        e = np.array([5.0, 20.0, 80.0, 400.0])
        back = stopping.energy_from_range(stopping.csda_range(e, "aluminum"), "aluminum")
        np.testing.assert_allclose(back, e, rtol=1e-3)
        res = stopping.residual_energy(np.array([10.0, 100.0]), 5.0, "aluminum")
        self.assertEqual(res[0], 0.0)                 # 10 MeV stops in 5 g/cm2 Al
        self.assertTrue(0 < res[1] < 100)

    def test_quality_factor_icrp60(self):
        q = stopping.icrp60_quality_factor(np.array([5.0, 50.0, 400.0]))
        np.testing.assert_allclose(q, [1.0, 0.32 * 50 - 2.2, 300 / np.sqrt(400)])


class Spectrum(unittest.TestCase):
    def test_recovers_integral_channels(self):
        e = [10.0, 30.0, 60.0]
        j = np.array([[1000.0, 120.0, 25.0]])
        d = differential_flux(e, j, stopping.GRID)
        for k, ek in enumerate(e):
            got = float(integral_from_differential(stopping.GRID, d, ek)[0])
            self.assertAlmostEqual(got / j[0, k], 1.0, delta=0.02)

    def test_nan_and_zero_rows(self):
        d = differential_flux([10.0, 30.0], np.array([[np.nan, 1.0], [0.0, 0.0]]), stopping.GRID)
        self.assertTrue(np.isnan(d[0]).all())
        self.assertTrue((d[1] == 0).all())


class Dose(unittest.TestCase):
    E = [10.0, 30.0, 60.0]
    J = np.array([[1000.0, 150.0, 40.0]])

    def test_more_shielding_less_dose(self):
        prev = None
        for t in [0.3, 2, 5, 10, 20, 40]:
            v = float(dose_rates(self.E, self.J, [(t, 1.0)]).rate_mgy_h["bfo"][0])
            if prev is not None:
                self.assertLess(v, prev)
            prev = v

    def test_deeper_organs_get_less(self):
        ds = dose_rates(self.E, self.J, [(1.0, 1.0)])
        self.assertGreater(ds.rate_mgy_h["skin"][0], ds.rate_mgy_h["eye"][0])
        self.assertGreater(ds.rate_mgy_h["eye"][0], ds.rate_mgy_h["bfo"][0])
        self.assertGreaterEqual(ds.rate_msv_h["bfo"][0], ds.rate_mgy_h["bfo"][0])   # Q >= 1

    def test_linear_in_flux_and_zero_at_zero(self):
        a = dose_rates(self.E, self.J, LOCATIONS["cabin"].shielding).rate_msv_h["bfo"][0]
        b = dose_rates(self.E, 3 * self.J, LOCATIONS["cabin"].shielding).rate_msv_h["bfo"][0]
        self.assertAlmostEqual(b / a, 3.0, places=6)
        z = dose_rates(self.E, np.zeros((1, 3)), LOCATIONS["cabin"].shielding).rate_msv_h["bfo"][0]
        self.assertEqual(z, 0.0)

    def test_kernel_matches_brute_force(self):
        """Residual-energy kernel vs a 2-million-point direct integration."""
        fine = np.geomspace(0.5, 3000, 2_000_000)
        jf = differential_flux(self.E, self.J, fine)[0]
        e1 = stopping.residual_energy(fine, 5.0, "aluminum")
        e2 = stopping.residual_energy(e1, 5.0, "water")
        s = np.where(e2 > 0, stopping.mass_stopping_power(np.maximum(e2, 0.5), "water"), 0)
        brute = np.sum(0.5 * (jf[1:] * s[1:] + jf[:-1] * s[:-1]) * np.diff(fine)) * 4 * np.pi * 1.602176634e-10 * 3600e3
        ours = float(dose_rates(self.E, self.J, [(5.0, 1.0)]).rate_mgy_h["bfo"][0])
        self.assertAlmostEqual(ours / brute, 1.0, delta=0.02)


if __name__ == "__main__":
    unittest.main()
