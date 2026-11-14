"""Crew health monitor: indicator models, assessment, causality, coupling to SHELTER."""

import copy
import io
import json
import math
import unittest

import numpy as np

from shelter.health import demo, models as m, monitor
from shelter.planner import engine
from shelter.data.synthetic import make_synthetic
from shelter.server import app


def log_with(checkins=None, events=None, **profile):
    return {"profile": profile, "checkins": checkins or [], "radiation_events": events or []}


class Radiation(unittest.TestCase):
    def test_cosmic_rays_only(self):
        led = m.radiation_ledger([], 10, gcr_msv_per_day=2.0)
        self.assertAlmostEqual(led["organs"]["bfo"]["d30_msv"], 20.0)
        self.assertAlmostEqual(led["organs"]["bfo"]["mission_msv"], 20.0)
        self.assertEqual(led["status"], m.OK)

    def test_windows_and_limits(self):
        ev = [{"day": 5, "bfo": 100, "eye": 0, "skin": 0}, {"day": 60, "bfo": 50, "eye": 0, "skin": 0}]
        led = m.radiation_ledger(ev, 60, gcr_msv_per_day=0.0)
        self.assertAlmostEqual(led["organs"]["bfo"]["d30_msv"], 50.0)        # day 5 is outside 30 days
        self.assertAlmostEqual(led["organs"]["bfo"]["year_msv"], 150.0)
        self.assertAlmostEqual(led["remaining30_bfo_msv"], 200.0)
        self.assertAlmostEqual(led["organs"]["bfo"]["frac30"], 50 / 250)

    def test_future_events_never_count(self):
        led = m.radiation_ledger([{"day": 20, "bfo": 900}], 10, gcr_msv_per_day=0.0)
        self.assertEqual(led["organs"]["bfo"]["mission_msv"], 0.0)
        self.assertFalse(led["ars_possible"])

    def test_status_levels_and_ars(self):
        self.assertEqual(m.radiation_ledger([{"day": 1, "bfo": 130}], 1, 0.0)["status"], m.WATCH)
        self.assertEqual(m.radiation_ledger([{"day": 1, "bfo": 210}], 1, 0.0)["status"], m.ACT)
        led = m.radiation_ledger([{"day": 1, "bfo": 800}], 1, 0.0)
        self.assertTrue(led["ars_possible"])
        self.assertEqual(led["remaining30_bfo_msv"], 0.0)

    def test_career(self):
        led = m.radiation_ledger([], 100, 1.0, prior_career_msv=500)
        self.assertAlmostEqual(led["career_msv"], 600.0)
        self.assertEqual(led["status"], m.ACT)


class Bone(unittest.TestCase):
    def test_leblanc_projection(self):
        b = m.bone(m.DAYS_PER_MONTH * 6, [], 60, planned_days=365)
        self.assertAlmostEqual(b["projected_unprotected_pct"]["trochanter"], -1.56 * 6)
        self.assertAlmostEqual(b["projected_unprotected_pct"]["lumbar spine"], -1.06 * 6)
        self.assertIsNone(b["adherence_7d"])
        self.assertEqual(b["status"], m.OK)
        self.assertLess(b["projected_end_pct"]["femoral neck"], -13)

    def test_adherence(self):
        self.assertEqual(m.bone(10, [60] * 7, 60)["status"], m.OK)
        self.assertEqual(m.bone(10, [40] * 7, 60)["status"], m.WATCH)
        self.assertEqual(m.bone(10, [20] * 7, 60)["status"], m.ACT)
        self.assertEqual(m.bone(10, [0] * 20 + [90] * 7, 60)["adherence_7d"], 1.0)   # capped, last 7 only

    def test_partial_gravity_note(self):
        self.assertTrue(m.bone(10, [], 60, gravity_g=0.38)["notes"])


class Co2(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(m.co2([])["status"], m.OK)
        self.assertEqual(m.co2([2.0] * 7)["status"], m.OK)
        self.assertEqual(m.co2([2.0] * 7, headaches_recent=True)["status"], m.WATCH)
        self.assertEqual(m.co2([2.8] * 7)["status"], m.WATCH)
        self.assertEqual(m.co2([2.0] * 6 + [3.4])["status"], m.ACT)

    def test_law2014_odds(self):
        self.assertAlmostEqual(m.co2([3.5] * 7)["headache_odds_x"], 2.0)
        self.assertAlmostEqual(m.co2([2.5] * 7)["headache_odds_x"], 1.0)


class Baselines(unittest.TestCase):
    def test_needs_baseline(self):
        self.assertIsNone(m.baseline_z([60, 61, 59]))
        self.assertIsNone(m.baseline_z([60] * 5))

    def test_z_and_floor(self):
        z = m.baseline_z([60] * 5 + [69])                    # SD floor 5 % of 60 = 3
        self.assertAlmostEqual(z["z"], 3.0)
        self.assertEqual(m.z_status(z, +1), m.ACT)
        self.assertEqual(m.z_status(z, -1), m.OK)
        self.assertEqual(m.z_status(None, +1), m.OK)

    def test_explicit_baseline(self):
        z = m.baseline_z([70], explicit={"mean": 60, "sd": 4})
        self.assertAlmostEqual(z["z"], 2.5)
        self.assertEqual(m.z_status(z, +1), m.WATCH)


class Heart(unittest.TestCase):
    def test_rmssd_sdnn_exact(self):
        rr = [800, 820] * 20                                    # alternating: RMSSD = 20, mean 810
        h = m.hrv(rr)
        self.assertAlmostEqual(h["rmssd_ms"], 20.0)
        self.assertAlmostEqual(h["hr_bpm"], 60000 / 810)
        self.assertAlmostEqual(h["sdnn_ms"], float(np.std(rr, ddof=1)))

    def test_artefacts_removed(self):
        rr = [800, 820] * 20 + [100, 4000, 1300]
        h = m.hrv(rr)
        self.assertEqual(h["beats"], 40)
        self.assertEqual(h["rejected"], 3)

    def test_too_few_beats(self):
        self.assertIsNone(m.hrv([800] * 10))


class Pvt(unittest.TestCase):
    def test_metrics(self):
        r = m.pvt([250, 300, 360, 600, 80], false_starts=1)
        self.assertEqual(r["n"], 4)
        self.assertEqual(r["lapses"], 2)                       # 360 and 600 >= 355 ms
        self.assertEqual(r["false_starts"], 2)                 # 80 ms counts as a false start
        self.assertAlmostEqual(r["mean_rt_ms"], (250 + 300 + 360 + 600) / 4)

    def test_no_valid(self):
        self.assertIsNone(m.pvt([50, 60]))


class Sleep(unittest.TestCase):
    def test_steady_eight_hours_is_one(self):
        self.assertAlmostEqual(m.sleep_pressure([8.0] * 20)["index"], 1.0, places=6)

    def test_thresholds_match_habitual_sleep(self):
        self.assertAlmostEqual(m.sleep_pressure([7.0] * 60)["index"], m.SLEEP_WATCH, places=4)
        self.assertEqual(m.sleep_pressure([5.0] * 30)["status"], m.ACT)
        self.assertEqual(m.sleep_pressure([7.5] * 30)["status"], m.OK)

    def test_recovery(self):
        debt = m.sleep_pressure([5.0] * 7)["index"]
        rec = m.sleep_pressure([5.0] * 7 + [9.0] * 4)["index"]
        self.assertLess(rec, debt)

    def test_steady_state_closed_form(self):
        s = m.S_WAKE_REF
        for _ in range(200):
            s = 1 - (1 - s) * math.exp(-16 / m.TAU_RISE_H)
            s = s * math.exp(-8 / m.TAU_DECAY_H)
        self.assertAlmostEqual(s, m.S_WAKE_REF, places=12)

    def test_wake_time_shifting(self):
        r = m.sleep_pressure([8] * 7, [7, 11, 3, 9, 5, 12, 2])
        self.assertGreater(r["wake_spread_h"], 1.5)
        self.assertEqual(r["status"], m.WATCH)
        self.assertLess(m.sleep_pressure([8] * 7, [7, 7.2, 6.9, 7, 7.1, 7, 7])["wake_spread_h"], 0.3)
        self.assertLess(m.sleep_pressure([8] * 7, [23.5, 0.5, 23.8, 0.2])["wake_spread_h"], 0.6)   # wraps midnight

    def test_empty(self):
        self.assertIsNone(m.sleep_pressure([]))


class Assessment(unittest.TestCase):
    def setUp(self):
        self.log = demo.demo_log()

    def test_demo_shape(self):
        a = monitor.assess(self.log)
        self.assertTrue(a["synthetic"])
        self.assertEqual(set(a["systems"]), {"immune", "bone", "cardiovascular", "behavioral"})
        self.assertEqual(set(a["stressors"]), {"radiation", "isolation", "gravity", "environment"})
        self.assertEqual(a["as_of_day"], 40)
        for act in a["actions"]:
            self.assertIn(act["severity"], (m.WATCH, m.ACT))
            self.assertTrue(act["source"])
        sev = [m._RANK[x["severity"]] for x in a["actions"]]
        self.assertEqual(sev, sorted(sev, reverse=True))
        json.dumps(a)                                           # serialisable

    def test_quiet_day_is_ok(self):
        a = monitor.assess(self.log, as_of_day=10)
        self.assertEqual(a["overall"], m.OK)
        self.assertEqual(a["actions"], [])

    def test_storm_day_flags_behavior_and_holds_eva(self):
        a = monitor.assess(self.log, as_of_day=22)
        self.assertEqual(a["systems"]["behavioral"]["status"], m.ACT)
        self.assertEqual(a["systems"]["cardiovascular"]["status"], m.ACT)
        self.assertTrue(a["flight_rules"]["overrides"]["crew_eva_hold"])

    def test_late_mission_co2_and_exercise(self):
        a = monitor.assess(self.log, as_of_day=40)
        self.assertEqual(a["stressors"]["environment"]["status"], m.ACT)
        self.assertEqual(a["systems"]["bone"]["status"], m.ACT)
        self.assertEqual(monitor.assess(self.log, as_of_day=38)["systems"]["immune"]["status"], m.WATCH)

    def test_no_look_ahead(self):
        """The assessment for day D must not change when anything after day D changes."""
        changed = copy.deepcopy(self.log)
        for c in changed["checkins"]:
            if c["day"] > 22:
                c.update(sleep_h=2.0, co2_mmhg=9.0, mood=0, stress=10, resting_hr=140, symptoms=["fever"])
        changed["radiation_events"].append({"day": 30, "bfo": 900.0})
        self.assertEqual(monitor.assess(self.log, 22), monitor.assess(changed, 22))
        self.assertNotEqual(monitor.assess(self.log, 40)["overall"], None)

    def test_empty_log(self):
        a = monitor.assess({})
        self.assertEqual(a["as_of_day"], 0)
        self.assertEqual(a["overall"], m.OK)
        self.assertIn("no test", a["systems"]["behavioral"]["indicators"][0]["value"])

    def test_fever_and_ars(self):
        a = monitor.assess(log_with([{"day": 3, "symptoms": ["fever", "bogus"]}],
                                    [{"day": 2, "bfo": 750}], gcr_msv_per_day=0))
        self.assertEqual(a["systems"]["immune"]["status"], m.ACT)
        texts = " ".join(x["text"] for x in a["actions"])
        self.assertIn("0.7 Gy", texts)
        self.assertIn("Fever", texts)
        self.assertTrue(a["radiation"]["ars_possible"])

    def test_hrv_from_wearable_and_baseline_building(self):
        cs = [{"day": d, "rr_ms": [800, 840] * 20} for d in range(1, 7)]
        cs.append({"day": 7, "rr_ms": [700, 702] * 20})            # HR up, HRV collapsed
        a = monitor.assess(log_with(cs))
        self.assertEqual(a["systems"]["cardiovascular"]["status"], m.ACT)
        self.assertEqual(len(a["trends"]["rmssd"]), 7)

    def test_pvt_baseline_and_protocols(self):
        good = {"rts": [250] * 50, "protocol": "pvt-b"}
        bad = {"rts": [250] * 40 + [600] * 10, "protocol": "pvt-b"}
        short = {"rts": [900] * 20, "protocol": "demo-60s", "duration_s": 60}
        cs = [{"day": d, "pvt": good} for d in (1, 2, 3)] + [{"day": 4, "pvt": short}]
        a = monitor.assess(log_with(cs))
        self.assertIn("building baseline", a["systems"]["behavioral"]["indicators"][0]["value"])
        self.assertEqual(a["systems"]["behavioral"]["status"], m.OK)     # the 60 s demo test is not compared
        a = monitor.assess(log_with(cs + [{"day": 5, "pvt": bad}]))
        self.assertEqual(a["systems"]["behavioral"]["status"], m.ACT)
        self.assertTrue(a["flight_rules"]["overrides"]["crew_eva_hold"])

    def test_only_short_tests(self):
        cs = [{"day": d, "pvt": {"rts": [260] * 20, "protocol": "demo-60s"}} for d in range(1, 6)]
        self.assertEqual(monitor.assess(log_with(cs))["pvt"]["protocol"], "demo-60s")

    def test_mood_and_stress(self):
        cs = [{"day": d, "mood": 7, "stress": 3} for d in range(1, 6)] + [{"day": 6, "mood": 2, "stress": 9}]
        a = monitor.assess(log_with(cs))
        self.assertEqual(a["stressors"]["isolation"]["status"], m.ACT)

    def test_short_sleep_and_stress_puts_immune_on_watch(self):
        cs = [{"day": d, "sleep_h": 8, "stress": 3} for d in range(1, 6)]
        cs += [{"day": d, "sleep_h": 4.5, "stress": 9} for d in range(6, 12)]
        a = monitor.assess(log_with(cs))
        self.assertEqual(a["systems"]["immune"]["status"], m.WATCH)
        self.assertTrue(any(x["system"] == "immune" for x in a["actions"]))

    def test_radiation_budget_tightens_rules(self):
        a = monitor.assess(log_with([], [{"day": 1, "bfo": 240}], gcr_msv_per_day=0))
        o = a["flight_rules"]["overrides"]
        self.assertAlmostEqual(o["shelter_trigger_max_msv"], 0.5)
        self.assertAlmostEqual(o["eva_start_bfo_max_msv"], 0.2)
        self.assertIn("stricter", a["flight_rules"]["reasons"][0])
        self.assertIn("standard storm rules apply", monitor.assess({})["flight_rules"]["reasons"][0])
        pol = monitor.apply_to_policy(engine.Policy(), a["flight_rules"])
        self.assertAlmostEqual(pol.shelter_trigger_msv, 0.5)
        self.assertAlmostEqual(pol.eva_start_bfo_msv, 0.2)
        loose = monitor.apply_to_policy(engine.Policy(shelter_trigger_msv=0.3), monitor.assess({})["flight_rules"])
        self.assertAlmostEqual(loose.shelter_trigger_msv, 0.3)            # never loosened


class Validation(unittest.TestCase):
    def test_rejects_bad_input(self):
        bad = [
            [1, 2], {"profile": 3}, {"checkins": "x"}, {"checkins": [3]},
            {"checkins": [{"day": -1}]}, {"checkins": [{"day": 1, "sleep_h": 30}]},
            {"checkins": [{"day": 1, "rr_ms": "800"}]}, {"checkins": [{"day": 1, "rr_ms": [float("nan")]}]},
            {"checkins": [{"day": 1, "pvt": 5}]}, {"checkins": [{"day": 1, "symptoms": "fever"}]},
            {"radiation_events": [{"bfo": 1}]}, {"radiation_events": "x"}, {"radiation_events": [7]},
            {"checkins": [{"day": 1}] * (monitor.MAX_CHECKINS + 1)},
            {"profile": {"gravity_g": 9}},
        ]
        for b in bad:
            with self.subTest(b=str(b)[:60]):
                with self.assertRaises((ValueError, TypeError)):
                    monitor.parse_log(b)

    def test_parse_is_idempotent(self):
        once = monitor.parse_log(demo.demo_log())
        self.assertEqual(monitor.parse_log(once), once)

    def test_unknown_symptoms_dropped_and_sorted(self):
        p = monitor.parse_log({"checkins": [{"day": 5, "symptoms": ["rash", "?"]}, {"day": 2}]})
        self.assertEqual([c["day"] for c in p["checkins"]], [2, 5])
        self.assertEqual(p["checkins"][1]["symptoms"], ["rash"])


class Coupling(unittest.TestCase):
    def test_crew_hold_blocks_eva_starts_in_replay(self):
        p = engine.prepare(make_synthetic())
        sched = [engine.Activity("EVA-Q", "EVA", 2.0, 2.0, max_delay_h=10)]   # quiet time, normally starts
        free = engine.run(p, sched, engine.Policy())
        held = engine.run(p, sched, engine.Policy(crew_eva_hold=True))
        self.assertEqual(free["activities"][0]["outcome"], "completed")
        self.assertEqual(held["activities"][0]["outcome"], "cancelled")
        self.assertTrue(any("not fit" in e["reason"] for e in held["log"]))


def call(method, path, body=None, query=""):
    data = b"" if body is None else json.dumps(body).encode()
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
           "CONTENT_LENGTH": str(len(data)), "wsgi.input": io.BytesIO(data)}
    got = {}
    out = b"".join(app.app(env, lambda s, h: got.update(code=int(s.split()[0]))))
    return got["code"], json.loads(out)


class Api(unittest.TestCase):
    def test_demo_meta_and_assess(self):
        code, log = call("GET", "/api/health/demo")
        self.assertEqual(code, 200)
        code, meta = call("GET", "/api/health/meta")
        self.assertEqual(meta["pvt"]["lapse_ms"], 355.0)
        code, a = call("POST", "/api/health", {"log": log, "as_of_day": 22})
        self.assertEqual((code, a["as_of_day"]), (200, 22))
        code, a = call("POST", "/api/health", log)                         # bare log also accepted
        self.assertEqual(a["as_of_day"], 40)

    def test_bad_input_is_400(self):
        self.assertEqual(call("POST", "/api/health", {"log": {"checkins": "x"}})[0], 400)
        self.assertEqual(call("POST", "/api/health", {"log": {}, "as_of_day": -5})[0], 400)

    def test_replay_with_crew_state(self):
        code, log = call("GET", "/api/health/demo")
        code, ev = call("GET", "/api/event", query="id=synthetic")
        code, r = call("POST", "/api/replay", {"event_id": "synthetic", "schedule": ev["default_schedule"],
                                               "health": log, "health_day": 22})
        self.assertEqual(code, 200)
        self.assertTrue(r["policy_used"]["crew_eva_hold"])
        self.assertTrue(r["crew_rules"]["reasons"])
        self.assertTrue(all(e["policy_outcome"] != "completed" for e in r["evas"]))
        code, r = call("POST", "/api/replay", {"event_id": "synthetic", "schedule": ev["default_schedule"]})
        self.assertIsNone(r["crew_rules"])


if __name__ == "__main__":
    unittest.main()
