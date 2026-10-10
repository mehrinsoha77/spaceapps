import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np

from shelter import config
from shelter.data import donki, events, omni, swpc
from shelter.data.series import FluxSeries, causal_background, fill_short_gaps
from tests.fakedata import omni_year_text, write_fake_cache


class OmniParser(unittest.TestCase):
    def test_parses_words_43_to_48_and_fill(self):
        gap = datetime(2012, 3, 7, 6)
        text = omni_year_text(2012, [(datetime(2012, 3, 7, 5), 4000.0, 1.9)], gap_hours={gap})
        times, flux = omni.parse_omni2(text, 2012)
        self.assertEqual(len(times), 366 * 24)                    # 2012 is a leap year
        i = int(np.where(times == np.datetime64("2012-03-07T06:00:00"))[0][0])
        self.assertTrue(np.isnan(flux[i]).all())                  # fill values -> NaN
        self.assertGreater(flux[i + 5, 3], 100)                   # >10 MeV during the storm
        self.assertAlmostEqual(flux[0, 3], 0.35, places=2)        # quiet level

    def test_big_1mev_values_are_not_fill(self):
        """Regression: word 43 (>1 MeV) has fill 999999.99, so 2e5 is a real value."""
        text = omni_year_text(2012, [(datetime(2012, 3, 7, 5), 4000.0, 1.9)])
        times, flux = omni.parse_omni2(text, 2012)
        i = int(np.where(times == np.datetime64("2012-03-07T10:00:00"))[0][0])
        self.assertGreater(flux[i, 0], 99999.99)
        self.assertFalse(np.isnan(flux[i]).any())

    def test_rejects_wrong_format(self):
        with self.assertRaises(omni.OmniFormatError):
            omni.parse_omni2("2012 1 0 1 2 3\n" * 50, 2012)


class SwpcParser(unittest.TestCase):
    def test_record_format(self):
        recs = [{"time_tag": "2026-10-10T08:00:00Z", "satellite": 18, "flux": 0.32, "energy": ">=10 MeV"},
                {"time_tag": "2026-10-10T08:00:00Z", "satellite": 18, "flux": 0.23, "energy": ">=100 MeV"},
                {"time_tag": "2026-10-10T08:05:00Z", "satellite": 18, "flux": None, "energy": ">=10 MeV"}]
        t, f = swpc.parse_swpc(recs)
        self.assertEqual(len(t), 2)
        self.assertAlmostEqual(f[0, swpc.LIVE_ENERGIES.index(10.0)], 0.32)
        self.assertTrue(np.isnan(f[1, swpc.LIVE_ENERGIES.index(10.0)]))


class DonkiMarkers(unittest.TestCase):
    def test_markers(self):
        m = donki.markers_from("FLR", [{"flrID": "x", "peakTime": "2012-03-07T00:24Z", "classType": "X5.4"}])
        self.assertEqual(m[0]["label"], "X5.4 flare")
        self.assertEqual(m[0]["time"], "2012-03-07T00:24:00")
        m = donki.markers_from("CME", [{"activityID": "c", "startTime": "2012-03-07T00:24Z",
                                        "cmeAnalyses": [{"isMostAccurate": True, "speed": 2684.0}]}])
        self.assertEqual(m[0]["label"], "CME 2684 km/s")


class Background(unittest.TestCase):
    def test_background_never_uses_future_data(self):
        hours = np.arange(300.0)
        a = np.ones((300, 2))
        b = a.copy()
        b[200:] = 1e4                                   # a huge storm in the "future"
        ba, bb = causal_background(a, hours), causal_background(b, hours)
        np.testing.assert_array_equal(ba[:200], bb[:200])

    def test_short_gaps_filled_long_gaps_kept(self):
        f = np.ones((20, 1))
        f[3:5] = np.nan
        f[10:16] = np.nan
        out = fill_short_gaps(f, max_gap=3)
        self.assertFalse(np.isnan(out[3:5]).any())
        self.assertTrue(np.isnan(out[10:16]).all())


class EventLoadingFromCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (config.CACHE_DIR, config.OFFLINE)
        config.CACHE_DIR = write_fake_cache(Path(self.tmp.name))
        config.OFFLINE = True

    def tearDown(self):
        config.CACHE_DIR, config.OFFLINE = self._old
        self.tmp.cleanup()

    def test_load_event_offline_with_markers(self):
        series, markers, status = events.load_event("2012-03")
        self.assertGreater(np.nanmax(series.channel(10.0)), 1000)
        self.assertEqual({m["kind"] for m in markers}, {"flare", "sep", "cme"})
        self.assertTrue((config.CACHE_DIR / "omni" / "omni2_2012_protons.npz").exists())
        avail = {e["id"]: e["cached"] for e in events.availability()}
        self.assertTrue(avail["2012-03"])
        self.assertFalse(avail["1989-10"])

    def test_live_from_cache(self):
        series, meta = swpc.load_live()
        self.assertTrue(meta["stale"])                  # offline -> served from cache, flagged
        self.assertEqual(series.energies, swpc.LIVE_ENERGIES)


if __name__ == "__main__":
    unittest.main()
