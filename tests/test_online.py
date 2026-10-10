"""The download path a fresh deployment uses: data fetched over HTTP on first use,
cached, and reused. A local HTTP server stands in for NASA SPDF, NASA DONKI and
NOAA SWPC, serving files in their real formats (made-up numbers)."""

import importlib.util
import json
import tempfile
import threading
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

from shelter import config
from shelter.data import events, omni, swpc
from tests.fakedata import write_fake_cache

ROOT = Path(__file__).resolve().parent.parent


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class Online(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        # what the "remote servers" hold, laid out like the real URLs
        src = write_fake_cache(base / "src")
        www = base / "www"
        (www / "omni").mkdir(parents=True)
        for f in (src / "omni").glob("*.dat"):
            f.rename(www / "omni" / f.name)
        (www / "swpc").mkdir()
        (src / "live" / "swpc_protons_7d.json").rename(www / "swpc" / "protons.json")
        (www / "donki2").mkdir()                       # primary DONKI host has nothing: 404
        for kind in ("FLR", "CME", "SEP"):
            recs = (src / "events" / "2012-03" / f"donki_{kind}_2012-03-06_2012-03-16.json").read_text()
            (www / "donki2" / kind).write_text(recs)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Quiet, directory=str(www)))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

        names = ("CACHE_DIR", "BUNDLED_DIR", "OFFLINE", "OMNI2_URL", "SWPC_PROTONS_URL",
                 "DONKI_PRIMARY", "DONKI_FALLBACK")
        self._old = {n: getattr(config, n) for n in names}
        config.CACHE_DIR = base / "cache"
        config.BUNDLED_DIR = base / "bundled"
        config.OFFLINE = False
        config.OMNI2_URL = url + "/omni/omni2_{year}.dat"
        config.SWPC_PROTONS_URL = url + "/swpc/protons.json"
        config.DONKI_PRIMARY = url + "/donki1/{kind}?startDate={start}&endDate={end}&api_key={key}"
        config.DONKI_FALLBACK = url + "/donki2/{kind}?startDate={start}&endDate={end}"

    def tearDown(self):
        for n, v in self._old.items():
            setattr(config, n, v)
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def test_first_use_downloads_then_reuses(self):
        self.assertFalse({e["id"]: e["cached"] for e in events.availability()}["2012-03"])
        self.assertTrue({e["id"]: e["loadable"] for e in events.availability()}["2012-03"])
        t = time.monotonic()
        series, markers, status = events.load_event("2012-03")
        self.assertLess(time.monotonic() - t, 10)          # a 404 from DONKI's first host is not retried
        self.assertGreater(np.nanmax(series.channel(10.0)), 1000)
        self.assertEqual({m["kind"] for m in markers}, {"flare", "sep", "cme"})
        self.assertTrue(all("network" in s for s in status["markers"].values()), status)
        compact = config.CACHE_DIR / "omni" / "omni2_2012_protons.npz"
        self.assertTrue(compact.exists())
        self.assertFalse((config.CACHE_DIR / "omni" / "omni2_2012.dat").exists())   # raw file not kept
        self.assertTrue({e["id"]: e["cached"] for e in events.availability()}["2012-03"])
        _, _, meta = omni.load_year(2012)
        self.assertEqual(meta["source"], "cache")

    def test_live_feed(self):
        series, meta = swpc.load_live()
        self.assertEqual(meta["source"], "network")
        self.assertFalse(meta["stale"])
        self.assertEqual(series.energies, swpc.LIVE_ENERGIES)

    def test_bundle_then_serve_without_network(self):
        events.load_event("2012-03")
        spec = importlib.util.spec_from_file_location("fetch_data", ROOT / "scripts" / "fetch_data.py")
        fetch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fetch)
        self.assertGreater(fetch.bundle(log=lambda *_: None), 0)
        self.assertTrue((config.BUNDLED_DIR / "omni" / "omni2_2012_protons.npz").exists())
        # a fresh deployment: empty cache, no network, bundled data only
        config.CACHE_DIR = Path(self.tmp.name) / "fresh-cache"
        config.OFFLINE = True
        self.assertTrue({e["id"]: e["cached"] for e in events.availability()}["2012-03"])
        series, markers, status = events.load_event("2012-03")
        self.assertGreater(np.nanmax(series.channel(10.0)), 1000)
        self.assertTrue(all(s == "bundled" for s in status["markers"].values()), status)
        self.assertEqual(omni.load_year(2012)[2]["source"], "bundled")


if __name__ == "__main__":
    unittest.main()
