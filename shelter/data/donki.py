"""NASA DONKI: flares, CMEs and SEP events used as timeline markers.

Tries api.nasa.gov first (needs NASA_API_KEY; DEMO_KEY is rate-limited), then
CCMC's own DONKI API, then the local cache.
"""

from .. import config
from .http import DataUnavailable, fetch_json

KINDS = ("FLR", "CME", "SEP")


def _fetch(kind, start, end, cache_dir):
    cache = cache_dir / f"donki_{kind}_{start}_{end}.json"
    urls = [config.DONKI_PRIMARY.format(kind=kind, start=start, end=end, key=config.NASA_API_KEY),
            config.DONKI_FALLBACK.format(kind=kind, start=start, end=end)]
    last = None
    for url in urls:
        try:
            data, meta = fetch_json(url, cache)
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
    for kind in kinds:
        try:
            recs, meta = _fetch(kind, start, end, cache_dir)
            markers += markers_from(kind, recs)
            status[kind] = meta.get("source", "?") + (" (stale)" if meta.get("stale") else "")
        except DataUnavailable as exc:
            status[kind] = f"unavailable: {exc}"
    markers.sort(key=lambda m: m["time"])
    return markers, status
