"""Paths, data-source URLs and runtime switches."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(os.environ.get("SHELTER_CACHE", ROOT / "data" / "cache"))
WEB_DIR = ROOT / "web"

# Set SHELTER_OFFLINE=1 on stage: no network calls at all, cache only.
OFFLINE = os.environ.get("SHELTER_OFFLINE", "0") == "1"

# Free key from https://api.nasa.gov (DEMO_KEY works but is heavily rate-limited).
NASA_API_KEY = os.environ.get("NASA_API_KEY", "DEMO_KEY")

HTTP_TIMEOUT_S = float(os.environ.get("SHELTER_HTTP_TIMEOUT", "25"))

# --- NASA SPDF: OMNI2 hourly merged data (includes GOES/IMP proton fluxes) ---
OMNI2_URL = "https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/omni2_{year}.dat"
OMNI2_FORMAT_URL = "https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/omni2.text"

# --- NOAA SWPC: real-time GOES integral protons (5-minute, last 7 days) ---
SWPC_PROTONS_URL = "https://services.swpc.noaa.gov/json/goes/primary/integral-protons-7-day.json"

# --- NASA DONKI (space weather event database) ---
DONKI_PRIMARY = "https://api.nasa.gov/DONKI/{kind}?startDate={start}&endDate={end}&api_key={key}"
# CCMC's own endpoint (new base URL from 2026-09-30); used when api.nasa.gov fails.
DONKI_FALLBACK = "https://ccmc.gsfc.nasa.gov/DONKI-API/get/{kind}?startDate={start}&endDate={end}"
