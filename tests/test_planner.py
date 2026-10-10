import unittest

import numpy as np

from shelter.data.series import FluxSeries
from shelter.data.synthetic import make_synthetic
from shelter.planner import engine


def quiet_series(hours=360):
    times = np.datetime64("2030-01-01T00:00:00") + np.arange(hours).astype("timedelta64[h]")
    flux = np.tile([2.0, 1.0, 0.6, 0.35, 0.25, 0.2], (hours, 1))
    return FluxSeries(times, [1.0, 2.0, 4.0, 10.0, 30.0, 60.0], flux, "test")


class Planner(unittest.TestCase):
    def setUp(self):
        self.series = make_synthetic()
        self.p = engine.prepare(self.series)
        self.window = float(self.p.hours[-1] - self.p.hours[self.p.t0_index])

    def test_policy_reduces_dose(self):
        r = engine.backtest(self.p, engine.default_schedule(self.window))
        for bound in ("hard", "soft"):
            b = r["bounds"][bound]
            self.assertLess(b["policy"]["bfo"], b["baseline"]["bfo"])
            self.assertLess(b["policy"]["skin"], b["baseline"]["skin"])

    def test_no_look_ahead(self):
        """Decisions before hour K must not change when the data after K changes."""
        k = self.p.t0_index + 60
        altered = make_synthetic()
        altered.flux[k + 1:] *= 50.0
        p2 = engine.prepare(altered)
        sched = engine.default_schedule(self.window)
        a = [e for e in engine.backtest(self.p, sched)["log"] if e["i"] <= k]
        b = [e for e in engine.backtest(p2, sched)["log"] if e["i"] <= k]
        self.assertEqual(a, b)
        self.assertGreater(len(a), 0)

    def test_no_look_ahead_across_a_data_gap(self):
        """Regression: gap filling once interpolated to the far side of a gap (future data)."""
        k = self.p.t0_index + 30                        # during the synthetic storm
        a, b = make_synthetic(), make_synthetic()
        a.flux[k - 1:k + 2] = np.nan                    # gap straddles hour K
        b.flux[k - 1:k + 2] = np.nan
        b.flux[k + 2:] *= 50.0                          # only data after K differ
        pa, pb = engine.prepare(a), engine.prepare(b)
        for place in engine.PLACES:
            np.testing.assert_array_equal(pa.rates["hard"][place]["bfo"][:k + 1],
                                          pb.rates["hard"][place]["bfo"][:k + 1])
        sched = engine.default_schedule(self.window)
        la = [e for e in engine.backtest(pa, sched)["log"] if e["i"] <= k]
        lb = [e for e in engine.backtest(pb, sched)["log"] if e["i"] <= k]
        self.assertEqual(la, lb)

    def test_data_gap_never_relaxes(self):
        """Missing data must not read as zero dose: no shelter exit, no EVA start during a gap."""
        i0 = self.p.t0_index
        s = make_synthetic()
        s.flux[i0 + 40:i0 + 52] = np.nan                # 12 h outage while the crew is sheltered
        s.flux[i0 + 4:i0 + 14] = np.nan                 # 10 h outage in quiet time
        p = engine.prepare(s)
        sched = [engine.Activity("EVA-Q", "EVA", 9.0, 2.0)]
        sim = engine.run(p, sched)
        gap = [i for i in range(i0 + 40, i0 + 52) if p.missing[i]]
        self.assertTrue(gap)
        self.assertTrue(all(sim["place"][i] == "shelter" for i in gap))
        self.assertTrue(any(e["action"] == "DATA_GAP" for e in sim["log"]))
        eva = sim["activities"][0]
        self.assertFalse(p.missing[i0 + int(eva["actual_start"])])
        self.assertGreater(eva["delay_h"], 0)

    def test_advise_without_data_gives_no_verdict(self):
        s = make_synthetic()
        i = self.p.t0_index + 30
        s.flux[i - 5:] = np.nan
        adv = engine.advise(engine.prepare(s), i)
        self.assertEqual({it["verdict"] for it in adv["items"]}, {"NO DATA"})

    def test_rising_from_quiet_counts_as_rising(self):
        """Regression: a storm rising out of zero SEP flux was 'not rising' for its first 3 h."""
        s = quiet_series()
        s.flux[200:] += 50.0 * (np.array(s.energies) / 10.0) ** -2.0
        p = engine.prepare(s)
        nc = engine.nowcast(p, 200, engine.Policy())
        self.assertTrue(nc["rising"])
        self.assertFalse(engine.nowcast(p, 199, engine.Policy())["rising"])

    def test_needless_eva_termination_is_a_false_alarm(self):
        pol = engine.Policy(eva_start_bfo_msv=1e9, eva_start_skin_msv=1e9, eva_block_if_s1_rising=False,
                            shelter_trigger_msv=1e9, eva_abort_bfo_msv=1e-9, eva_abort_skin_msv=1e-9,
                            false_alarm_msv=1e9)
        r = engine.backtest(self.p, [engine.Activity("EVA-T", "EVA", 26.0, 6.0)], pol)
        self.assertEqual(r["evas"][0]["policy_outcome"], "terminated")
        self.assertIn("eva_terminate", [d["kind"] for d in r["false_alarms"]["details"]])

    def test_reacts_within_hours_of_onset(self):
        """Regression: dose and shelter must start when protons arrive, not a day later."""
        r = engine.backtest(self.p, engine.default_schedule(self.window))
        onset = np.datetime64(r["first_s1_utc"].rstrip("Z"))
        act = np.datetime64(r["first_action"]["utc"].rstrip("Z"))
        self.assertLessEqual((act - onset) / np.timedelta64(1, "h"), 3)

    def test_missing_low_channel_does_not_blank_dose(self):
        s = make_synthetic()
        s.flux[:, 0] = np.nan                       # >1 MeV channel entirely missing
        p = engine.prepare(s)
        np.testing.assert_allclose(p.rates["hard"]["cabin"]["bfo"], self.p.rates["hard"]["cabin"]["bfo"])

    def test_baseline_never_shelters(self):
        sim = engine.run(self.p, engine.default_schedule(self.window), apply_policy=False)
        self.assertNotIn("shelter", set(sim["place"]))

    def test_burn_is_not_interrupted(self):
        sched = [engine.Activity("BURN-1", "BURN", 26.0, 3.0, max_delay_h=0)]
        sim = engine.run(self.p, sched)
        i0 = self.p.t0_index
        rel = self.p.hours - self.p.hours[i0]
        during = [sim["place"][i] for i in range(i0, len(rel) - 1) if 26.0 <= rel[i] < 29.0]
        self.assertTrue(during and all(pl == "cabin" for pl in during))
        self.assertTrue(any(e["action"] == "BURN_START" for e in sim["log"]))

    def test_quiet_conditions_no_actions(self):
        p = engine.prepare(quiet_series())
        r = engine.backtest(p, engine.default_schedule(150))
        self.assertEqual([e["action"] for e in r["log"] if e["action"] not in ("EVA_START", "BURN_START", "BURN_END")], [])
        self.assertEqual(r["false_alarms"]["count"], 0)
        self.assertAlmostEqual(r["bounds"]["hard"]["baseline"]["bfo"], 0.0)

    def test_eva_cancelled_after_max_delay(self):
        sched = [engine.Activity("EVA-X", "EVA", 30.0, 6.0, max_delay_h=4.0)]
        r = engine.backtest(self.p, sched)
        self.assertEqual(r["evas"][0]["policy_outcome"], "cancelled")

    def test_projection_closed_form(self):
        pol = engine.Policy(growth_cap=10.0)
        # persistence
        self.assertAlmostEqual(engine.projected_dose(2.0, 0.0, 0, 5, pol), 10.0)
        # growth with cap: numeric check
        k = 0.5
        tau = np.linspace(0, 12, 200001)
        num = getattr(np, "trapezoid", None) or np.trapz
        num = num(np.minimum(np.exp(k * tau), 10.0) * 1.0, tau)
        self.assertAlmostEqual(engine.projected_dose(1.0, k, 0, 12, pol), num, places=3)

    def test_advise_outputs(self):
        i = self.p.t0_index + 30          # during the synthetic storm
        adv = engine.advise(self.p, i, eva_duration_h=6)
        kinds = {it["kind"]: it["verdict"] for it in adv["items"]}
        self.assertEqual(kinds["EVA"], "NO-GO")
        self.assertEqual(kinds["SHELTER"], "SHELTER")


if __name__ == "__main__":
    unittest.main()
