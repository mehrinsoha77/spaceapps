# SHELTER

Turns NASA and NOAA solar-storm data into crew schedule decisions (hold an EVA, end it, move to the storm shelter) and tests those decisions by replaying real historical storms hour by hour, never looking ahead.

Built for the NASA Space Apps Challenge 2026. **Full write-up: [SOLUTION.md](SOLUTION.md).**

## Quick start

```bash
pip install -r requirements.txt          # only NumPy; Python 3.10+
export NASA_API_KEY=your_key             # free at https://api.nasa.gov (optional; DEMO_KEY is rate-limited)
python scripts/fetch_data.py             # download + cache all data (needs internet once)
python -m shelter.server.app             # open http://127.0.0.1:8000
```

Offline / on stage: `SHELTER_OFFLINE=1 python -m shelter.server.app` uses cached data only.

Tests: `python -m unittest discover -s tests -t .`
Backtest every cached storm: `python scripts/run_backtest.py`

## Data

- NASA SPDF OMNI2 hourly proton fluxes (historical storms)
- NOAA SWPC real-time GOES integral protons (live mode)
- NASA DONKI flares, CMEs and SEP events (timeline markers)
- MSL/RAD cruise measurements (Guo et al. 2015) for validation

## License

MIT, see LICENSE.
