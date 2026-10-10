"""End-to-end: real HTTP server on a free port, fake cache, offline mode."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from shelter import config
from shelter.server import app
from tests.fakedata import write_fake_cache


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls._old = (config.CACHE_DIR, config.OFFLINE)
        config.CACHE_DIR = write_fake_cache(Path(cls.tmp.name))
        config.OFFLINE = True
        app._PREP_CACHE.clear()
        app._LIVE_CACHE.update(t=0, value=None)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        config.CACHE_DIR, config.OFFLINE = cls._old
        app._PREP_CACHE.clear()
        cls.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=30) as r:
            return json.loads(r.read())

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def test_meta(self):
        m = self.get("/api/meta")
        self.assertIn("cabin", m["locations"])
        self.assertTrue(any(e["id"] == "2012-03" and e["cached"] for e in m["events"]))

    def test_event_and_replay(self):
        ev = self.get("/api/event?id=2012-03")
        self.assertEqual(len(ev["times"]), len(ev["channels"]["10"]))
        self.assertTrue(ev["markers"])
        res = self.post("/api/replay", {"event_id": "2012-03", "schedule": ev["default_schedule"], "policy": {}})
        self.assertGreater(res["bounds"]["hard"]["saved"]["bfo"], 0)
        self.assertEqual(len(res["place_policy"]), len(ev["times"]))

    def test_live(self):
        live = self.get("/api/live?eva_h=6")
        self.assertTrue(live["data_meta"]["stale"])
        self.assertEqual(len(live["advice"]["items"]), 3)

    def test_validation_runs(self):
        v = self.get("/api/validation")
        self.assertEqual(len(v["rows"]), 3)
        self.assertTrue(all(r["predicted_mid_msv"] > 0 for r in v["rows"]))

    def test_errors_are_clean(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/api/event?id=nope")
        self.assertEqual(cm.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post("/api/replay", {"event_id": "2012-03", "schedule": [{"kind": "XYZ", "start_h": 1, "duration_h": 1}]})
        self.assertEqual(cm.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/../shelter/config.py")
        self.assertEqual(cm.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
