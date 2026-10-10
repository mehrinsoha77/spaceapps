"""SHELTER web server: Python standard library only (no framework to install).

Run:  python -m shelter.server.app            (http://127.0.0.1:8000)
      SHELTER_OFFLINE=1 python -m shelter.server.app   (cache only, for the stage)

The same request handling is exposed as a WSGI `app`, which is what Vercel runs
(see api/index.py and vercel.json).
"""

import argparse
import json
import mimetypes
import threading
import time
import traceback
from dataclasses import asdict, fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np

from .. import config
from ..data import donki, events, swpc
from ..data.http import DataUnavailable
from ..data.omni import OmniFormatError
from ..physics import dose as dose_mod
from ..physics.limits import GCR_CRUISE_MSV_PER_DAY, GCR_SOURCE, NOAA_S_SCALE, REFERENCE_LIMITS
from ..planner import engine
from ..validation import rad

_PREP_CACHE = {}
_LIVE_CACHE = {"t": 0, "value": None}
_PREP_LOCK = threading.Lock()      # one storm download/preparation at a time
_LIVE_LOCK = threading.Lock()      # separate, so the live tab never waits behind a storm download


def _jsonable(o):
    if isinstance(o, (np.floating,)):
        v = float(o)
        return None if not np.isfinite(v) else round(v, 6)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return [_jsonable(x) for x in o.tolist()]
    if isinstance(o, float):
        return None if not np.isfinite(o) else round(o, 6)
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(x) for x in o]
    return o


def _prepared(event_id):
    with _PREP_LOCK:
        if event_id not in _PREP_CACHE:
            series, markers, status = events.load_event(event_id)
            _PREP_CACHE[event_id] = (series, markers, status, engine.prepare(series))
        return _PREP_CACHE[event_id]


def _number(v, name, lo=0.0, hi=1e6):
    """A finite float in [lo, hi], or ValueError (-> HTTP 400)."""
    x = float(v)
    if not np.isfinite(x) or not lo <= x <= hi:
        raise ValueError(f"{name} must be a number between {lo:g} and {hi:g}, got {v!r}")
    return x


def _policy_from(d):
    pol = engine.Policy()
    if d is None:
        return pol
    if not isinstance(d, dict):
        raise ValueError("policy must be a JSON object")
    names = {f.name for f in fields(engine.Policy)}
    for k, v in d.items():
        if k not in names:
            continue
        cur = getattr(pol, k)
        if isinstance(cur, bool):
            setattr(pol, k, v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on"))
        else:
            setattr(pol, k, type(cur)(_number(v, k)))
    return pol


MAX_ACTIVITIES = 50


def _schedule_from(items):
    if items is None:
        return []
    if not isinstance(items, list) or len(items) > MAX_ACTIVITIES:
        raise ValueError(f"schedule must be a list of at most {MAX_ACTIVITIES} activities")
    acts = []
    for n, a in enumerate(items):
        if not isinstance(a, dict):
            raise ValueError("each activity must be a JSON object")
        kind = str(a.get("kind", "EVA")).upper()
        if kind not in ("EVA", "BURN"):
            raise ValueError(f"activity kind must be EVA or BURN, got {kind}")
        if "start_h" not in a or "duration_h" not in a:
            raise ValueError("each activity needs start_h and duration_h")
        acts.append(engine.Activity(
            id=str(a.get("id") or f"{kind}-{n + 1}")[:40], kind=kind,
            start_h=_number(a["start_h"], "start_h"),
            duration_h=_number(a["duration_h"], "duration_h", 0.1, 1000),
            max_delay_h=_number(a.get("max_delay_h", 48.0), "max_delay_h"),
            ingress_min=_number(a.get("ingress_min", 30.0), "ingress_min", 0, 600)))
    return acts


# ------------------------------------------------------------------ handlers

def api_meta(_q, _b):
    return {
        "locations": {k: {"name": v.name, "shielding": v.shielding, "mean_g_cm2": v.mean_thickness(),
                          "source": v.source} for k, v in dose_mod.LOCATIONS.items()},
        "targets": dose_mod.TARGET_DEPTHS,
        "limits": REFERENCE_LIMITS,
        "gcr": {"msv_per_day": GCR_CRUISE_MSV_PER_DAY, "source": GCR_SOURCE},
        "s_scale": NOAA_S_SCALE,
        "policy_defaults": asdict(engine.Policy()),
        "events": events.availability(),
        "offline": config.OFFLINE,
        "sources": {"omni2": config.OMNI2_URL, "swpc": config.SWPC_PROTONS_URL,
                    "donki": config.DONKI_PRIMARY.split("?")[0], "rad": events.RAD_SOURCE},
    }


def api_event(q, _b):
    eid = q.get("id", [""])[0]
    series, markers, status, p = _prepared(eid)
    i0 = p.t0_index
    sl = slice(i0, None)
    ch = {str(int(e)): series.flux[sl, k] for k, e in enumerate(series.energies)}
    window_h = float(p.hours[-1] - p.hours[i0])
    return {
        "id": eid, "event": events.get_event(eid), "times": p.times_iso[i0:],
        "hours": p.hours[sl] - p.hours[i0], "channels": ch, "sep10": p.j10[sl],
        "rates": {place: {t: p.rates["hard"][place][t][sl] for t in engine.TARGETS} for place in engine.PLACES},
        "rates_soft": {place: {"bfo": p.rates["soft"][place]["bfo"][sl]} for place in engine.PLACES},
        "markers": markers, "status": status, "notes": series.notes, "synthetic": series.synthetic,
        "source": series.source, "window_h": window_h,
        "default_schedule": [asdict(a) for a in engine.default_schedule(window_h)],
    }


def api_replay(_q, body):
    eid = body.get("event_id")
    if not isinstance(eid, str):
        raise ValueError("event_id must be a string")
    series, markers, status, p = _prepared(eid)
    policy = _policy_from(body.get("policy"))
    sched = _schedule_from(body.get("schedule"))
    res = engine.backtest(p, sched, policy)
    res["policy_used"] = asdict(policy)
    res["synthetic"] = series.synthetic
    return res


def api_live(q, _b):
    eva_h = _number(q.get("eva_h", ["6"])[0], "eva_h", 0.25, 24)
    now = time.time()
    with _LIVE_LOCK:
        if _LIVE_CACHE["value"] is None or now - _LIVE_CACHE["t"] > 240:
            series, meta = swpc.load_live()
            p = engine.prepare(series, t0=str(series.times[-1] - np.timedelta64(48, "h")))
            end = str(series.times[-1])[:10]
            start = str(series.times[-1] - np.timedelta64(7, "D"))[:10]
            try:
                markers, mstatus = donki.load_markers(start, end, config.CACHE_DIR / "live")
            except Exception as exc:  # markers are optional
                markers, mstatus = [], {"error": str(exc)}
            _LIVE_CACHE.update(t=now, value=(series, meta, p, markers, mstatus))
        series, meta, p, markers, mstatus = _LIVE_CACHE["value"]
    i = len(p.hours) - 1
    while i > 0 and p.missing[i]:          # advise from the latest sample that has dose data
        i -= 1
    adv = engine.advise(p, i, _policy_from(json.loads(q.get("policy", ["{}"])[0])), eva_duration_h=eva_h)
    i0 = p.t0_index
    return {
        "latest_utc": p.times_iso[i], "data_meta": meta, "source": series.source,
        "advice": adv, "times": p.times_iso[i0:], "hours": p.hours[i0:] - p.hours[i0],
        "channels": {str(int(e)): series.flux[i0:, k] for k, e in enumerate(series.energies)},
        "rates": {place: {"bfo": p.rates["hard"][place]["bfo"][i0:]} for place in engine.PLACES},
        "markers": markers, "marker_status": mstatus,
    }


def api_validation(_q, _b):
    return rad.run_benchmark()


ROUTES = {
    ("GET", "/api/meta"): api_meta,
    ("GET", "/api/event"): api_event,
    ("POST", "/api/replay"): api_replay,
    ("GET", "/api/live"): api_live,
    ("GET", "/api/validation"): api_validation,
}

JSON = "application/json"
MAX_BODY = 1 << 20        # replay requests are a few kB; refuse anything absurd


def _data_hint():
    if config.OFFLINE:
        return "Run `python scripts/fetch_data.py` while online to fill the cache."
    return ("The NASA/NOAA data server could not be reached. Try again in a minute, "
            "or pick the SYNTHETIC self-test storm.")


def dispatch(method, path, query="", body=b""):
    """Handle one request. Returns (status, payload bytes, content type).

    Shared by the standard-library server below and the WSGI app (Vercel and other
    hosts), so every deployment answers identically. Never raises.
    """
    fn = ROUTES.get((method, path))
    if fn is None:
        if method in ("GET", "HEAD") and not path.startswith("/api/"):
            return _static(path)
        if any(p == path for _, p in ROUTES):
            return 405, _dumps({"error": f"{method} not allowed on {path}"}), JSON
        return 404, _dumps({"error": "not found"}), JSON
    try:
        payload = json.loads(body or b"{}") if method == "POST" else {}
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return 200, _dumps(fn(parse_qs(query), payload)), JSON
    except KeyError as exc:
        return 404, _dumps({"error": f"unknown id {exc}"}), JSON
    except (DataUnavailable, OmniFormatError) as exc:
        return 503, _dumps({"error": str(exc), "hint": _data_hint()}), JSON
    except (ValueError, TypeError) as exc:
        return 400, _dumps({"error": str(exc)}), JSON
    except Exception as exc:  # never crash the demo server
        traceback.print_exc()
        return 500, _dumps({"error": f"{type(exc).__name__}: {exc}"}), JSON


def _dumps(payload):
    return json.dumps(_jsonable(payload)).encode()


def _static(path):
    rel = "index.html" if path in ("", "/") else path.lstrip("/")
    target = (config.WEB_DIR / rel).resolve()
    if not target.is_relative_to(config.WEB_DIR.resolve()) or not target.is_file():
        return 404, _dumps({"error": "not found"}), JSON
    ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return 200, target.read_bytes(), ctype


_REASONS = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed",
            413: "Payload Too Large", 500: "Internal Server Error", 503: "Service Unavailable"}


def app(environ, start_response):
    """WSGI entry point (Vercel's Python runtime, gunicorn, waitress, ...)."""
    method = environ.get("REQUEST_METHOD", "GET").upper()
    try:
        n = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        n = 0
    if n > MAX_BODY:
        code, data, ctype = 413, _dumps({"error": "request body too large"}), JSON
    else:
        body = environ["wsgi.input"].read(n) if n > 0 else b""
        code, data, ctype = dispatch(method, environ.get("PATH_INFO") or "/",
                                     environ.get("QUERY_STRING", ""), body)
    start_response(f"{code} {_REASONS.get(code, 'Error')}",
                   [("Content-Type", ctype), ("Content-Length", str(len(data))),
                    ("Cache-Control", "no-store")])
    return [b"" if method == "HEAD" else data]


class Handler(BaseHTTPRequestHandler):
    server_version = "SHELTER/1.0"

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}")

    def _handle(self, method):
        url = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            code, data, ctype = 413, _dumps({"error": "request body too large"}), JSON
        else:
            code, data, ctype = dispatch(method, url.path, url.query, self.rfile.read(n) if n else b"")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(data)

    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("HEAD")

    def do_POST(self):
        self._handle("POST")


def serve(host="127.0.0.1", port=8000):
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"SHELTER running at http://{host}:{port}  (offline mode: {config.OFFLINE})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    serve(a.host, a.port)
