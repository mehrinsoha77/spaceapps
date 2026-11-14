# SHELTER

**Crew health monitoring for long missions.** Astronauts gather their own health indicators (a daily check-in, a 3-minute reaction-time test and a pulse count in the browser, heart-beat intervals from any wearable, cabin CO₂ readings) and SHELTER turns them into a clear status and actions across the four spaceflight stressors (space radiation, isolation and confinement, altered gravity, closed environment) and four health systems (immune, bone, cardiovascular, behavioral). Its radiation side reads NASA and NOAA solar-storm data, computes the dose in the suit, cabin and storm shelter, and decides when to hold an EVA, end it or shelter, adjusted to the astronaut’s own dose budget and alertness. Every decision is tested by replaying real storms hour by hour, never looking ahead.

Built for the NASA Space Apps Challenge 2026, challenge “Create Health Monitoring Software for Astronauts on Space Missions”. **Full write-up: [SOLUTION.md](SOLUTION.md).**

> **AI use.** Parts of this project’s code, tests and documentation were generated with an AI assistant (Claude, Anthropic) and reviewed by the team.

## Crew health tab

Open the app: the **Crew health** tab shows a synthetic demo astronaut (red banner) so every indicator is visible. Drag the day slider to see what the monitor knew on any day. Then press **Start my own log** and:

1. Fill in today’s check-in (sleep, wake time, mood, stress, exercise, CO₂, resting heart rate; paste RR intervals from a wearable for HRV).
2. Take the **3-minute reaction test (PVT-B)** or the 60-second demo version; tap along with your pulse for 15 s if you have no heart-rate reading.
3. Save. After 5 check-ins (4 reaction tests) the monitor has your personal baseline and flags changes.
4. On **Replay a storm**, tick “Apply the crew health state” to see SHELTER shelter earlier and hold EVAs for a tired or dose-limited crew member.

The log is saved only in your browser (export/import as JSON). Each assessment is computed by the server, which keeps nothing; run `python -m shelter.server.app` on a laptop and the whole health monitor works with no internet at all. Indicators, thresholds and sources: Method and sources tab, and `shelter/health/models.py`.

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
