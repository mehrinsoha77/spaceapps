"""NASA DONKI: flares, CMEs and SEP events used as timeline markers.

Tries api.nasa.gov first (needs NASA_API_KEY; DEMO_KEY is rate-limited), then
CCMC's own DONKI API, then the local cache.
"""

import json
from concurrent.futures import ThreadPoolExecutor

from .. import config
from .http import DataUnavailable, bundled_path, fetch_json

KINDS = ("FLR", "CME", "SEP")


def _fetch(kind, start, end, cache_dir):
    cache = cache_dir / f"donki_{kind}_{start}_{end}.json"
    bundled = bundled_path(cache)
    if bundled is not None:
        return json.loads(bundled.read_text()), {"source": "bundled", "stale": False}
    urls = [config.DONKI_PRIMARY.format(kind=kind, start=start, end=end, key=config.NASA_API_KEY),
            config.DONKI_FALLBACK.format(kind=kind, start=start, end=end)]
    last = None
    for url in urls:
        try:
            data, meta = fetch_json(url, cache, retries=0, timeout=config.MARKER_TIMEOUT_S)
            if isinstance(data, list):
                return data, meta
        except DataUnavailable as exc:
            last = exc
        except ValueError as exc:      # HTML error page instead of JSON
            last = exc
    raise DataUnavailable(f"DONKI {kind} unavailable: {last}")


def _z(t):
    if not t:
        return None
    t = str(t).replace("Z", "")
    return t if len(t) > 16 else t + ":00"


def markers_from(kind, records):
    out = []
    for r in records:
        if kind == "FLR":
            t = _z(r.get("peakTime") or r.get("beginTime"))
            out.append({"time": t, "kind": "flare", "label": f"{r.get('classType', '?')} flare",
                        "id": r.get("flrID")})
        elif kind == "SEP":
            inst = (r.get("instruments") or [{}])[0].get("displayName", "")
            out.append({"time": _z(r.get("eventTime")), "kind": "sep", "label": f"SEP onset ({inst})",
                        "id": r.get("sepID")})
        elif kind == "CME":
            speed = None
            for a in r.get("cmeAnalyses") or []:
                if a.get("isMostAccurate") and a.get("speed"):
                    speed = a["speed"]
            label = f"CME {int(speed)} km/s" if speed else "CME"
            out.append({"time": _z(r.get("startTime")), "kind": "cme", "label": label,
                        "id": r.get("activityID")})
    return [m for m in out if m["time"]]


def load_markers(start, end, cache_dir, kinds=KINDS):
    """Return (markers, status). Missing kinds are reported, never fatal."""
    markers, status = [], {}

    def one(kind):
        try:
            return kind, _fetch(kind, start, end, cache_dir), None
        except (DataUnavailable, ValueError, OSError) as exc:
            return kind, None, exc

    with ThreadPoolExecutor(max_workers=len(kinds) or 1) as pool:   # the kinds are independent
        results = list(pool.map(one, kinds))
    for kind, got, exc in results:
        if got is None:
            status[kind] = f"unavailable: {exc}"
            continue
        recs, meta = got
        markers += markers_from(kind, recs)
        status[kind] = meta.get("source", "?") + (" (stale)" if meta.get("stale") else "")
    markers.sort(key=lambda m: m["time"])
    return markers, status
