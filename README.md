# SHELTER

Turns NASA and NOAA solar-storm data into crew schedule decisions (hold an EVA, end it, move to the storm shelter) and tests those decisions by replaying real historical storms hour by hour, never looking ahead.

Built for the NASA Space Apps Challenge 2026. **Full write-up: [SOLUTION.md](SOLUTION.md).**

## Quick start (local)

```bash
pip install -r requirements.txt          # only NumPy; Python 3.10+
export NASA_API_KEY=your_key             # free at https://api.nasa.gov (optional; DEMO_KEY is rate-limited)
python scripts/fetch_data.py             # download + cache all data (needs internet once)
python -m shelter.server.app             # open http://127.0.0.1:8000
```

Offline / on stage: `SHELTER_OFFLINE=1 python -m shelter.server.app` uses cached data only.

Tests: `python -m unittest discover -s tests -t .`
Backtest every cached storm: `python scripts/run_backtest.py`

## Deploy on Vercel

1. Import this GitHub repository at [vercel.com/new](https://vercel.com/new). Keep the default settings: `vercel.json` already sets the framework to "Other", serves `public/` as the site and sends `/api/*` to the Python function `api/index.py` (Python 3.12 + NumPy).
2. Optional: add the environment variable `NASA_API_KEY` (Settings → Environment Variables).
3. Deploy and open the URL. Each storm is downloaded from NASA SPDF the first time it is opened (a few seconds), then cached.

To make the deployment independent of NASA's servers (recommended before judging):

```bash
python scripts/fetch_data.py --bundle    # copies the storm data into data/bundled/ (~2 MB)
git add data/bundled && git commit -m "Bundle storm data" && git push
```

Preview deployments ask visitors to log in to Vercel unless Deployment Protection is turned off; the production URL is public.

## Data

- NASA SPDF OMNI2 hourly proton fluxes (historical storms)
- NOAA SWPC real-time GOES integral protons (live mode)
- NASA DONKI flares, CMEs and SEP events (timeline markers)
- MSL/RAD cruise measurements (Guo et al. 2015) for validation

## License

MIT, see LICENSE.
