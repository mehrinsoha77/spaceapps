"""Paths, data-source URLs and runtime switches."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "public"

# Serverless hosts (Vercel sets VERCEL=1) only allow writes under /tmp.
SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
_DEFAULT_CACHE = Path("/tmp/shelter-cache") if SERVERLESS else ROOT / "data" / "cache"
CACHE_DIR = Path(os.environ.get("SHELTER_CACHE", _DEFAULT_CACHE))

# Read-only copy of the historical data committed with the code
# (`python scripts/fetch_data.py --bundle`). Checked before the cache and the network,
# so a deployment does not depend on NASA servers being reachable during a demo.
BUNDLED_DIR = Path(os.environ.get("SHELTER_BUNDLED", ROOT / "data" / "bundled"))

# Set SHELTER_OFFLINE=1 on stage: no network calls at all, cache only.
OFFLINE = os.environ.get("SHELTER_OFFLINE", "0") == "1"

# Free key from https://api.nasa.gov (DEMO_KEY works but is heavily rate-limited).
NASA_API_KEY = os.environ.get("NASA_API_KEY", "DEMO_KEY")

HTTP_TIMEOUT_S = float(os.environ.get("SHELTER_HTTP_TIMEOUT", "20"))
# Event markers are optional: give up on DONKI quickly rather than hold up a page.
MARKER_TIMEOUT_S = float(os.environ.get("SHELTER_MARKER_TIMEOUT", "8"))

# --- NASA SPDF: OMNI2 hourly merged data (includes GOES/IMP proton fluxes) ---
OMNI2_URL = "https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/omni2_{year}.dat"
OMNI2_FORMAT_URL = "https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/omni2.text"

# --- NOAA SWPC: real-time GOES integral protons (5-minute, last 7 days) ---
SWPC_PROTONS_URL = "https://services.swpc.noaa.gov/json/goes/primary/integral-protons-7-day.json"

# --- NASA DONKI (space weather event database) ---
DONKI_PRIMARY = "https://api.nasa.gov/DONKI/{kind}?startDate={start}&endDate={end}&api_key={key}"
# CCMC's own endpoint (new base URL from 2026-09-30); used when api.nasa.gov fails.
DONKI_FALLBACK = "https://ccmc.gsfc.nasa.gov/DONKI-API/get/{kind}?startDate={start}&endDate={end}"
