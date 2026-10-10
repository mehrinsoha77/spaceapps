"""Network fetch with a file cache that doubles as the offline fallback.

Every successful download is written to disk. If the network fails (or
SHELTER_OFFLINE=1), the last good copy is used and the result is marked stale,
so the UI can say so instead of pretending the data is live.
"""

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import config


class DataUnavailable(RuntimeError):
    pass


def _ssl_context():
    ctx = ssl.create_default_context()
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        path = os.environ.get(var)
        if path and Path(path).exists():
            ctx.load_verify_locations(path)
    return ctx


def _download(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "SHELTER/1.0 (NASA Space Apps)"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        return resp.read()


def fetch_bytes(url, cache_path, max_age_s=None, retries=1, timeout=None):
    """Return (bytes, meta). meta = {source: network|cache, stale, fetched_at, error}."""
    cache_path = Path(cache_path)
    meta_path = cache_path.with_suffix(cache_path.suffix + ".meta.json")
    if cache_path.exists() and max_age_s is not None and meta_path.exists():
        # fresh enough to reuse without a download (age comes from the download record,
        # so a cache file with no record is never treated as fresh)
        age = time.time() - meta_path.stat().st_mtime
        if age < max_age_s:
            return cache_path.read_bytes(), _read_meta(meta_path, "cache", stale=False)

    error = "offline mode" if config.OFFLINE else None
    if not config.OFFLINE:
        for attempt in range(retries + 1):
            try:
                data = _download(url, timeout or config.HTTP_TIMEOUT_S)
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
                tmp.write_bytes(data)
                tmp.replace(cache_path)
                meta = {"source": "network", "stale": False, "url": url,
                        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                meta_path.write_text(json.dumps(meta))
                return data, meta
            except Exception as exc:  # network, HTTP, TLS: all fall through to cache
                error = f"{type(exc).__name__}: {exc}"
                if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500 and exc.code != 429:
                    break                     # a client error will not fix itself on retry
                time.sleep(min(2 ** attempt, 4) if attempt < retries else 0)

    if cache_path.exists():
        meta = _read_meta(meta_path, "cache", stale=True)
        meta["error"] = error
        return cache_path.read_bytes(), meta
    raise DataUnavailable(f"{url} unavailable and no cached copy ({error})")


def fetch_json(url, cache_path, max_age_s=None, retries=1, timeout=None):
    data, meta = fetch_bytes(url, cache_path, max_age_s, retries=retries, timeout=timeout)
    return json.loads(data.decode("utf-8")), meta


def bundled_path(cache_path):
    """The read-only bundled copy of a cache file, if one was committed with the code."""
    try:
        rel = Path(cache_path).resolve().relative_to(config.CACHE_DIR.resolve())
    except ValueError:
        return None
    path = config.BUNDLED_DIR / rel
    return path if path.is_file() else None


def _read_meta(meta_path, source, stale):
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except ValueError:
            meta = {}
    meta["source"] = source
    meta["stale"] = stale
    return meta
