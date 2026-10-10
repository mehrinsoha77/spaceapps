"""Deployment wiring: Vercel config, the serverless entry point, and the WSGI app."""

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shelter import config
from shelter.server import app
from tests.fakedata import write_fake_cache

ROOT = Path(__file__).resolve().parent.parent


def call(method, path, body=None, query=""):
    """Run one request through the WSGI app the way a WSGI server would."""
    data = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
               "CONTENT_LENGTH": str(len(data)), "wsgi.input": io.BytesIO(data)}
    got = {}

    def start_response(status, headers):
        got["status"], got["headers"] = int(status.split()[0]), dict(headers)

    out = b"".join(app.app(environ, start_response))
    return got["status"], got["headers"], out


class VercelConfig(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / "vercel.json").read_text())

    def test_static_output_has_the_page(self):
        out = ROOT / self.cfg["outputDirectory"]
        for f in ("index.html", "app.js", "style.css"):
            self.assertTrue((out / f).is_file(), f)
        self.assertEqual(out.resolve(), config.WEB_DIR.resolve())   # local server serves the same files

    def test_api_routes_to_the_python_function(self):
        self.assertIn({"source": "/api/(.*)", "destination": "/api/index"}, self.cfg["rewrites"])
        for pattern in self.cfg["functions"]:
            self.assertTrue((ROOT / pattern).is_file(), pattern)

    def test_every_api_path_the_page_calls_exists(self):
        js = (ROOT / "public" / "app.js").read_text()
        called = set(re.findall(r"[\"`](/api/[a-z]+)", js))
        served = {path for _, path in app.ROUTES}
        self.assertTrue(called)
        self.assertLessEqual(called, served)

    def test_entry_point_exposes_the_wsgi_app(self):
        spec = importlib.util.spec_from_file_location("vercel_entry", ROOT / "api" / "index.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertIs(mod.app, app.app)

    def test_serverless_cache_goes_to_tmp(self):
        env = {k: v for k, v in os.environ.items() if k != "SHELTER_CACHE"}
        env["VERCEL"] = "1"
        out = subprocess.run([sys.executable, "-c", "from shelter import config; print(config.CACHE_DIR)"],
                             cwd=ROOT, env=env, capture_output=True, text=True, check=True).stdout.strip()
        self.assertTrue(out.startswith("/tmp/"), out)


class Wsgi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls._old = (config.CACHE_DIR, config.OFFLINE, config.BUNDLED_DIR)
        config.CACHE_DIR = write_fake_cache(Path(cls.tmp.name) / "cache")
        config.BUNDLED_DIR = Path(cls.tmp.name) / "bundled"
        config.OFFLINE = True
        app._PREP_CACHE.clear()
        app._LIVE_CACHE.update(t=0, value=None)

    @classmethod
    def tearDownClass(cls):
        config.CACHE_DIR, config.OFFLINE, config.BUNDLED_DIR = cls._old
        app._PREP_CACHE.clear()
        app._LIVE_CACHE.update(t=0, value=None)
        cls.tmp.cleanup()

    def test_page_and_assets(self):
        code, headers, body = call("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"SHELTER", body)
        self.assertEqual(call("GET", "/app.js")[0], 200)
        self.assertEqual(call("HEAD", "/")[2], b"")

    def test_full_replay_flow(self):
        code, _, body = call("GET", "/api/meta")
        self.assertEqual(code, 200)
        meta = json.loads(body)
        self.assertTrue(all(e["loadable"] for e in meta["events"] if e["cached"]))
        code, _, body = call("GET", "/api/event", query="id=synthetic")
        self.assertEqual(code, 200)
        ev = json.loads(body)
        code, _, body = call("POST", "/api/replay", {"event_id": "synthetic", "schedule": ev["default_schedule"],
                                                     "policy": {"shelter_trigger_msv": 2.0,
                                                                "eva_block_if_s1_rising": False}})
        self.assertEqual(code, 200)
        res = json.loads(body)
        self.assertEqual(res["policy_used"]["shelter_trigger_msv"], 2.0)
        self.assertFalse(res["policy_used"]["eva_block_if_s1_rising"])
        self.assertGreater(res["bounds"]["hard"]["saved"]["bfo"], 0)

    def test_live_and_validation(self):
        code, _, body = call("GET", "/api/live", query="eva_h=4")
        self.assertEqual(code, 200)
        self.assertEqual(len(json.loads(body)["advice"]["items"]), 3)
        self.assertEqual(call("GET", "/api/validation")[0], 200)

    def test_bad_input_is_a_clean_400(self):
        bad = [
            ("POST", "/api/replay", b"{not json", ""),
            ("POST", "/api/replay", [1, 2], ""),
            ("POST", "/api/replay", {"event_id": "synthetic", "policy": "x"}, ""),
            ("POST", "/api/replay", {"event_id": "synthetic", "schedule": [{"kind": "EVA", "start_h": 1,
                                                                            "duration_h": "NaN"}]}, ""),
            ("POST", "/api/replay", {"event_id": "synthetic", "schedule": [{"kind": "EVA"}]}, ""),
            ("POST", "/api/replay", {"event_id": ["synthetic"]}, ""),
            ("GET", "/api/live", None, "eva_h=-3"),
        ]
        for method, path, body, query in bad:
            with self.subTest(body=body, query=query):
                code, _, out = call(method, path, body, query)
                self.assertEqual(code, 400, out)
                self.assertIn("error", json.loads(out))

    def test_unknown_routes(self):
        self.assertEqual(call("GET", "/api/nope")[0], 404)
        self.assertEqual(call("GET", "/api/replay")[0], 405)
        self.assertEqual(call("GET", "/api/event", query="id=1999-01")[0], 404)
        self.assertEqual(call("GET", "/../shelter/config.py")[0], 404)

    def test_missing_data_is_503_with_a_hint(self):
        code, _, body = call("GET", "/api/event", query="id=2017-09")      # not in the fake cache, offline
        self.assertEqual(code, 503)
        self.assertIn("hint", json.loads(body))


if __name__ == "__main__":
    unittest.main()
