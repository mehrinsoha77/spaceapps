"""SHELTER web server: Python standard library only (no framework to install).

Run:  python -m shelter.server.app            (http://127.0.0.1:8000)
      SHELTER_OFFLINE=1 python -m shelter.server.app   (cache only, for the stage)
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
_LOCK = threading.Lock()


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
    with _LOCK:
        if event_id not in _PREP_CACHE:
            series, markers, status = events.load_event(event_id)
            _PREP_CACHE[event_id] = (series, markers, status, engine.prepare(series))
        return _PREP_CACHE[event_id]


def _policy_from(d):
    pol = engine.Policy()
    names = {f.name for f in fields(engine.Policy)}
    for k, v in (d or {}).items():
        if k in names:
            cur = getattr(pol, k)
            setattr(pol, k, type(cur)(v) if not isinstance(cur, bool) else bool(v))
    return pol


def _schedule_from(items):
    acts = []
    for n, a in enumerate(items or []):
        kind = str(a.get("kind", "EVA")).upper()
        if kind not in ("EVA", "BURN"):
            raise ValueError(f"activity kind must be EVA or BURN, got {kind}")
        acts.append(engine.Activity(
            id=str(a.get("id") or f"{kind}-{n + 1}"), kind=kind,
            start_h=float(a["start_h"]), duration_h=float(a["duration_h"]),
            max_delay_h=float(a.get("max_delay_h", 48.0)), ingress_min=float(a.get("ingress_min", 30.0))))
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
    series, markers, status, p = _prepared(eid)
    policy = _policy_from(body.get("policy"))
    sched = _schedule_from(body.get("schedule"))
    res = engine.backtest(p, sched, policy)
    res["policy_used"] = asdict(policy)
    res["synthetic"] = series.synthetic
    return res


def api_live(q, _b):
    eva_h = float(q.get("eva_h", ["6"])[0])
    now = time.time()
    with _LOCK:
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


class Handler(BaseHTTPRequestHandler):
    server_version = "SHELTER/1.0"

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}")

    def _send(self, code, payload, ctype="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(_jsonable(payload)).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method):
        url = urlparse(self.path)
        fn = ROUTES.get((method, url.path))
        if fn is None:
            if method == "GET":
                return self._static(url.path)
            return self._send(404, {"error": "not found"})
        try:
            body = {}
            if method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
            return self._send(200, fn(parse_qs(url.query), body))
        except KeyError as exc:
            return self._send(404, {"error": f"unknown id {exc}"})
        except (DataUnavailable, OmniFormatError) as exc:
            return self._send(503, {"error": str(exc),
                                    "hint": "Run `python scripts/fetch_data.py` while online to fill the cache."})
        except (ValueError, TypeError) as exc:
            return self._send(400, {"error": str(exc)})
        except Exception as exc:  # never crash the demo server
            traceback.print_exc()
            return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (config.WEB_DIR / rel).resolve()
        if not target.is_relative_to(config.WEB_DIR.resolve()) or not target.is_file():
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        return self._send(200, target.read_bytes(), ctype)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


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
