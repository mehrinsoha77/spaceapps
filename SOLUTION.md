# SHELTER — the complete solution, A to Z

**SHELTER turns NASA and NOAA solar-storm data into crew schedule decisions — hold this EVA, end that one, move to the storm shelter now — and proves each rule by replaying real historical storms hour by hour without looking ahead.**

Target: NASA Space Apps Challenge 2026 (14–15 November), astronaut-health challenge.
Stack: Python 3.10+ and NumPy only. No framework, no database, no internet needed on stage.

---

## A. Read this first: what is verified and what is not

| Claim | Status |
|---|---|
| Proton stopping power and range match NIST PSTAR within 1.3% for water, 10–200 MeV | **Verified** by unit test |
| Dose engine matches a 2-million-point brute-force integration within 2% | **Verified** by unit test |
| Decisions never use future data | **Verified**: changing every value after hour K leaves all decisions up to K identical (unit test) |
| Parsers read the real OMNI2, SWPC and DONKI formats | Formats taken from the official OMNI2 format document and a live SWPC record; tested against files built in those formats |
| Real-storm results (dose saved, false alarms, RAD comparison) | **Not yet measured.** The build environment could not download NASA data. Run `python scripts/fetch_data.py` and `python scripts/run_backtest.py` on your laptop. **Quote only the numbers those scripts print.** |
| "World-first" | **No.** See section C. The honest claim is narrower and still strong |
| "Guaranteed to win" | Nobody can promise that. This is built to score well on all five judging criteria |

**Hackathon rule to respect.** Space Apps judges work done during the event (14–15 Nov), and the full challenge statement only comes out on 28 October. Use this codebase to learn the science, the data and the stack now. Then build your submission during the event, adapted to the official statement and its listed datasets. Check the 2026 Participant Terms and the Project Submission Guide (published 13 Nov) for the exact rules.

---

## B. The problem

Outside Earth's magnetic field, a large solar particle event (SEP) can deliver a crew's normal *month* of radiation in hours. The danger depends on **where each astronaut is** when the protons arrive:

- in a ~0.3 g/cm² spacesuit on an EVA (spacewalk),
- in a lightly shielded cabin (~10 g/cm²), or
- in a storm shelter (~30 g/cm²).

Missions to the Moon and Mars will have long EVAs and no Earth magnetosphere. Flight controllers need clear answers: *should we start this EVA? end it? shelter now?* Each answer has a cost (lost EVA time, disrupted schedule), so the rules must be both protective **and** proven not to cry wolf.

**Who it's for:** flight controllers and mission planners (Artemis, Gateway, future Mars crews), and the public/education side through the replay view.

---

## C. What is new (and what is not)

Existing NASA and community tools:

- **MissionDPT** (NASA JSC): web tool that projects mission dose, with UMASEP SEP forecasts and GOES proton data since 1986.
- **ARRT** (Acute Radiation Risks Tool): projects organ doses from onboard dosimeters in real time.
- **CCMC SEP Scoreboard**: shows real-time SEP forecasts from many models side by side.
- **SpaceGenes+** (2025 Space Apps Best Use of Science): dashboard on how radiation and microgravity affect astronaut health at the molecular level.

**SHELTER's contribution:**

1. It turns dose into **schedule decisions** for a specific crew timeline (EVAs, a non-interruptible burn, shelter time).
2. It runs a **no-look-ahead backtest** over historical storms. The decision rules see only past data, are scored on what really happened, and show both sides: dose avoided, and EVA hours lost or false alarms.
3. It runs a **public check of the dose engine** against radiation measured inside a real spacecraft on its way to Mars (MSL/RAD).
4. Every number on screen traces to a cited source or a unit test.

Say "partially novel: a decision layer and an honest evaluation on top of established physics". Judges trust that more than "world-first".

---

## D. NASA and partner data used

| Data | Agency / host | Used for | Access |
|---|---|---|---|
| **OMNI2 hourly merged data**, proton flux > 1, 2, 4, 10, 30, 60 MeV (words 43–48) | NASA SPDF (Goddard) | Historical storm replay, RAD benchmark | `https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/omni2_YYYY.dat` |
| **GOES integral protons**, 5-min, last 7 days (≥1 … ≥500 MeV) | NOAA SWPC | Live mode | `https://services.swpc.noaa.gov/json/goes/primary/integral-protons-7-day.json` |
| **DONKI** flares, CMEs, SEP events | NASA (CCMC) | Timeline markers, context | `https://api.nasa.gov/DONKI/...` with fallback `https://ccmc.gsfc.nasa.gov/DONKI-API/get/...` (new CCMC base URL since 30 Sep 2026) |
| **MSL/RAD cruise SEP doses** (4.0, 19.5, 1.2 mSv) and the RAD shielding distribution | NASA MSL mission (Guo et al. 2015, A&A 577 A58) | Validation target | Published values |
| **NASA-STD-3001** limits (600 mSv career; 250 mSv SPE shelter design threshold) | NASA OCHMO | Reference lines | Technical brief |
| **NIST PSTAR** proton stopping powers | NIST | Physics unit tests | Published table values |

Get a free NASA API key at api.nasa.gov and set `NASA_API_KEY`. The `DEMO_KEY` default is heavily rate-limited.

---

## E. How it works (pipeline)

```
 GOES protons (OMNI2 hourly / SWPC 5-min)          DONKI flares, CMEs, SEPs
            │                                                │
            ▼                                                │
 1. Causal background removal ── 10th percentile of the     │
    previous 7 days, per channel (never future data)        │
            │                                                │
            ▼                                                │
 2. Spectrum ── piecewise power law through the ≥10 MeV     │
    integral channels; "hard" and "soft" high-energy tails  │
            │                                                │
            ▼                                                │
 3. Transport ── slow each proton through the shield        │
    (Al-equivalent thickness distribution) and then body    │
    tissue (skin 0.007, eye 0.3, BFO 5 g/cm²); score dose   │
    and ICRP-60 dose equivalent                              │
            │                                                │
            ▼                                                │
 4. Dose-rate series for EVA suit, cabin, storm shelter     │
            │                                                │
            ▼                                                ▼
 5. Nowcast at hour t (data ≤ t only): current rate, 3-h trend → "rising" and "decaying" projections
            │
            ▼
 6. Flight rules → HOLD EVA / TERMINATE EVA / SHELTER / LEAVE SHELTER (burns are never interrupted)
            │
            ▼
 7. Backtest: the same real data scores "follow the schedule" vs "with SHELTER"
    → dose avoided, EVA hours lost, false alarms, decision log
```

---

## F. The physics, in plain terms (with the equations)

**1. Stopping power (how fast a proton loses energy).** Bethe formula for protons:

`S/ρ = K · (Z/A) · (1/β²) · [ ½·ln(2·mₑc²·β²γ²·T_max / I²) − β² ]`, with K = 0.307075 MeV cm²/mol.

Water: Z/A = 0.555, I = 75 eV. Aluminium: Z/A = 0.482, I = 166 eV. Shell and density-effect corrections are left out; the PSTAR test shows the error is ≤1.3% where it matters.

**2. Range (how far it gets).** CSDA range `R(E) = ∫ dE / S(E)`. A proton of energy E₀ crossing thickness t leaves with energy E₁, where `R(E₁) = R(E₀) − t`. If `R(E₀) < t` it stops. (10 MeV stops in 0.17 g/cm² of aluminium; 100 MeV goes through 10 g/cm².)

**3. Spectrum from integral channels.** GOES gives `J(>E)` at a few thresholds. Between channels, `J(>E) = J_k·(E/E_k)^(−γ_k)`, so the differential spectrum is `j(E) = γ·J(>E)/E`. Above the top channel the last slope continues ("hard") or steepens by 1 ("soft"). Neither is always the higher dose: a soft spectrum puts the same protons at lower energies, which deposit more behind thin shielding and less behind thick shielding. SHELTER shows both.

**4. Dose behind shielding.** For isotropic intensity j(E) (per steradian) and a shield described as thickness `t_i` over solid-angle fraction `f_i`:

`Ḋ = 4π · 1.602×10⁻¹⁰ · Σ_i f_i ∫ j(E₀) · S_w(E₂) dE₀`  (Gy/s)

E₂ is the energy left after the aluminium and then the tissue depth. Done naively, this integral under-samples the Bragg peak: protons that only just reach the organ deposit the most. SHELTER integrates over the residual energy instead, using the exact CSDA identity

`S_w(E₂) dE₀ = S_Al(E₀) · S_w(E₁)/S_Al(E₁) dE₂`,

which makes the integrand smooth. A unit test checks this against brute force.

**5. Dose equivalent.** ICRP-60 quality factor of the residual proton's LET L (keV/µm): Q = 1 below 10; `0.32L − 2.2` up to 100; `300/√L` above.

**6. Cosmic rays.** Galactic cosmic rays are added as a constant 1.75 mSv/day, the RAD cruise measurement. Schedule changes can't reduce it, and SHELTER says so.

**7. Locations (Al-equivalent shielding distributions):**

| Place | Distribution | Basis |
|---|---|---|
| EVA suit | 0.3 g/cm² everywhere | Team assumption (no credit for the vehicle blocking the sky: conservative) |
| Crew cabin | 5 (30%), 10 (50%), 20 (20%) | Team assumption, mean ≈ 10.5 |
| Storm shelter | 20 (30%), 30 (50%), 50 (20%) | Team assumption, mean ≈ 31 |
| MSL cruise (RAD) | 3 (30%), 9 (50%), 50 (20%) | Guo et al. 2015: ~30% < 5, 50% at 8–10, 20% ≥ 20, mean ≈ 16 |

**What is deliberately NOT modelled:** secondary neutrons and nuclear fragments; real 3D geometry; the difference between Earth (where GOES is) and a spacecraft far from Earth; flare forecasting before protons arrive. Say this out loud. Judges reward it.

---

## G. Decision rules (defaults are team choices, editable in the UI)

Every hour SHELTER computes, from data up to that hour only:

- `k` = log-slope of the ≥10 MeV SEP flux over the last 3 h
- **Rising projection:** `rate·e^(kτ)`, capped at 10× the current rate (used for decisions)
- **Decaying projection:** `rate·e^(−τ/24h)` (shown for context)

| Rule | Default |
|---|---|
| Move to shelter if projected cabin BFO dose over the next 12 h ≥ | 1.0 mSv |
| Leave shelter when cabin BFO rate < 0.02 mSv/h for 3 h and not rising | — |
| Hold an EVA start if projected EVA BFO dose ≥ / skin dose ≥ | 0.5 mSv / 5 mSv |
| Hold an EVA start while ≥10 MeV ≥ 10 pfu (NOAA S1) and rising | on |
| Terminate a running EVA if projected remaining BFO / skin dose ≥ | 1.0 / 10 mSv (30-min ingress counted) |
| Cancel an EVA if still unsafe after its maximum delay | 48 h |
| Burns are non-interruptible | crew leaves shelter for the burn; the extra dose is logged |
| False alarm = an action that avoided < | 0.1 mSv in hindsight |

Thresholds are **not** NASA flight rules; those aren't public in this form. The point is that SHELTER makes the trade-off **visible**: change a threshold, rerun, and see dose avoided vs EVA hours lost vs false alarms.

---

## H. Proof it works (validation plan and results to fill in)

1. **Physics unit tests** (done): PSTAR agreement, range inversion, Q(L), monotonic dose with shielding and depth, linearity, brute-force kernel check.
2. **No-look-ahead test** (done): decisions before hour K are identical when all data after K are changed.
3. **Regression tests** (done): e.g. OMNI's >1 MeV word has a different fill value (999999.99). An early version treated large real values as missing and reacted a day late. A test now guards this.
4. **MSL/RAD benchmark** (run on your laptop): `python scripts/fetch_data.py` prints SHELTER vs RAD for Jan, Mar and May 2012, plus a leave-one-out calibration. Expect agreement within a factor of 2–3 at best, because GOES is at Earth and MSL was not. Show the chart exactly as it comes out.
5. **Historical backtest** (run on your laptop): `python scripts/run_backtest.py` covers Oct 1989, Jul 2000, Nov 2001, Oct–Nov 2003, Jan 2005, Jan/Mar/May 2012 and Sep 2017. Copy the totals line into your slides:
   *"Across N storms, SHELTER cut blood-forming-organ dose by X% for Y hours of EVA delay and Z false alarms, using thresholds A and B."*

---

## I. Software architecture

```
shelter/
├── shelter/
│   ├── config.py              data URLs, cache folder, offline switch, API key
│   ├── physics/
│   │   ├── stopping.py        Bethe stopping power, CSDA range, Q(L)
│   │   ├── spectrum.py        integral channels → differential spectrum
│   │   ├── dose.py            shielding distributions, organ depths, dose kernels
│   │   └── limits.py          NASA-STD-3001 / NCRP reference limits, NOAA S-scale
│   ├── data/
│   │   ├── http.py            download + file cache + offline fallback (marks stale data)
│   │   ├── omni.py            NASA SPDF OMNI2 parser (55 words; per-word fill values)
│   │   ├── swpc.py            NOAA SWPC live GOES JSON parser
│   │   ├── donki.py           NASA DONKI markers (api.nasa.gov → CCMC fallback → cache)
│   │   ├── series.py          time series, gap filling, causal background, ≥10 MeV channels
│   │   ├── events.py          storm catalog, RAD values, prefetch
│   │   └── synthetic.py       labelled SYNTHETIC self-test storm (red banner in UI)
│   ├── planner/engine.py      nowcast, flight rules, simulation, backtest, live advice
│   ├── validation/rad.py      MSL/RAD benchmark + leave-one-out calibration
│   └── server/app.py          standard-library HTTP server + JSON API + static files
├── web/                       index.html, style.css, app.js (hand-drawn canvas charts, no CDN)
├── scripts/fetch_data.py      download + check everything (run while online)
├── scripts/run_backtest.py    backtest all cached storms → data/backtest_results.csv
└── tests/                     34 unittest tests (physics, data, planner, live server)
```

**API**

| Method | Path | Returns |
|---|---|---|
| GET | `/api/meta` | Locations, limits, policy defaults, storm list with cache status, data sources |
| GET | `/api/event?id=2012-03` | Flux channels, SEP flux, dose-rate series, DONKI markers, default schedule |
| POST | `/api/replay` | `{event_id, schedule, policy}` → backtest: doses, EVA outcomes, false alarms, decision log, crew-location timelines |
| GET | `/api/live?eva_h=6` | Latest GOES status, EVA GO/NO-GO, shelter call, minutes-to-abort, last 48 h, DONKI events |
| GET | `/api/validation` | MSL/RAD comparison table and caveats |

Missing data returns HTTP 503 with the fix ("run fetch_data.py"). Bad input returns 400. The server never crashes on a request.

**UI screens:** Replay a storm (flux chart with DONKI markers, crew-location strips, time scrubber, "what SHELTER knew at this hour" panel, outcome cards, decision log) · Live now · Check against Mars cruise · Method and sources.

---

## J. Run it

```bash
# 1. Python 3.10+ and NumPy
pip install -r requirements.txt

# 2. Download all data while online (OMNI2, SWPC, DONKI) and print the RAD check
export NASA_API_KEY=your_key            # Windows PowerShell: $env:NASA_API_KEY="your_key"
python scripts/fetch_data.py

# 3. Start the app → open http://127.0.0.1:8000
python -m shelter.server.app

# 4. Stage mode: no network calls at all, cached data only
SHELTER_OFFLINE=1 python -m shelter.server.app     # PowerShell: $env:SHELTER_OFFLINE="1"; python -m shelter.server.app

# 5. Tests and backtest
python -m unittest discover -s tests -t .
python scripts/run_backtest.py
```

If a storm shows "not downloaded yet", rerun step 2. The SYNTHETIC storm always works offline. It is only for checking the software and carries a red banner: never present its numbers.

---

## K. The pitch

**30 seconds.** "When a solar storm hits a crew beyond Earth, the question isn't *how much radiation is out there*. It's *should this astronaut be outside right now?* SHELTER reads NASA and NOAA proton data, works out the dose in a suit, a cabin and a shelter, and tells flight control when to hold an EVA, end it, or shelter. We replayed real storms hour by hour, never letting it see the future, and it cut organ dose by [X]% for [Y] hours of EVA delay. And we checked the dose engine against radiation measured inside Curiosity's spacecraft on its way to Mars."

**3-minute live demo**

| Time | Do | Say |
|---|---|---|
| 0:00 | Replay tab, March 2012 loaded | "A real storm. NASA OMNI2 proton data; flare and CME markers from NASA DONKI." |
| 0:25 | Point at the EVA schedule and the burn | "One astronaut, six planned EVAs and a burn that can't be interrupted." |
| 0:40 | Click **Run replay** | "SHELTER now steps through hour by hour and only sees the past." |
| 0:55 | Drag the scrubber to the first shelter decision | "Here: S3 storm, flux rising. It projected over 10 mSv in 12 h and moved the crew to shelter." |
| 1:20 | Point at the two strips | "Top: what happened if you follow the schedule. Bottom: with SHELTER. Blue is shelter time; magenta EVAs moved off the storm." |
| 1:40 | Outcome cards | "Dose avoided, *and* the cost: EVA hours lost, false alarms. We show both." |
| 2:00 | Open thresholds, raise the shelter trigger, rerun | "Mission planners can tune the trade-off live." |
| 2:20 | Validation tab | "Is the dose engine real? This is measured radiation inside MSL. Here's how close we get, and why it's not perfect." |
| 2:45 | Method tab | "Every number traces to NASA data or a unit test. What we don't model is listed." |

Record a backup screen video of this, and set `SHELTER_OFFLINE=1` on stage.

---

## L. Questions judges will ask, and honest answers

- **"Isn't this what MissionDPT/ARRT do?"** Those project dose for flight controllers. SHELTER is the decision layer on top: it turns dose into schedule changes and publishes a no-look-ahead backtest of those decisions.
- **"GOES is at Earth. Your spacecraft isn't."** Correct. Near Earth (ISS, the Moon, Gateway) GOES is a good proxy. For Mars transit it isn't, and the RAD comparison shows the size of that error. The fix is to add a spacecraft-local feed: an onboard dosimeter or a heliospheric SEP model.
- **"Why no secondary neutrons?"** They need full transport codes (HZETRN, Geant4). We stated it. The RAD calibration factor absorbs part of it, and an OLTARIS response function can replace our kernel later.
- **"Why not AI?"** The decision has to be auditable by a flight director, and there are about ten large storms to learn from: far too few to train a model honestly. Simple, testable rules beat a black box here.
- **"Isn't your projection just a heuristic?"** Yes. It's labelled as one, and the backtest measures how good it is. Replacing it with CCMC SEP Scoreboard forecasts is the next step.
- **"How do you know there's no look-ahead?"** There's a unit test that changes all future data and checks that earlier decisions don't move.

---

## M. 48-hour build plan for the event (4–6 people)

| Role | Hours 0–12 | 12–28 | 28–40 | 40–48 |
|---|---|---|---|---|
| Lead / science | Read the official statement; map its datasets to SHELTER | Physics + validation | Freeze numbers | Q&A rehearsal |
| Data | Fetch + cache all data, check formats | Add any datasets the statement lists | Offline test | — |
| Planner | Rules + backtest | Tune thresholds via backtest | Lock defaults | — |
| Front end | Replay screen | Live + validation screens | Polish, mobile | — |
| Story / video | Slides outline | Draft video | Record backup demo | Submit project page |

Submission checklist: public repository link, demo video or slides as the 2026 guide requires, an English project page that names **every NASA and partner dataset used**, and a team of 6 or fewer.

---

## N. Limitations and next steps

1. Spacecraft-local radiation (Mars transit): ingest a heliospheric SEP model or onboard dosimeter data.
2. Forecasts before onset: add CCMC SEP Scoreboard probabilities (email CCMC and the model developers first, as their rules of the road ask).
3. Transport: swap the 1D kernel for OLTARIS/HZETRN response functions, which include secondaries.
4. Body geometry: use a computational phantom's thickness distribution per organ instead of a single depth.
5. Multiple crew members and real EVA timelines from Artemis planning documents.

---

## O. Sources

- NASA Space Apps 2026 dates and challenge summary — spaceappschallenge.org participant FAQ; therecursive.com (8 Oct 2026)
- Judging criteria (impact, creativity, validity, relevance, presentation) — Space Apps Judging & Awards Guide
- OMNI2 format (words 43–48 proton flux, fill values) — spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/omni2.text
- SWPC GOES integral protons JSON — services.swpc.noaa.gov/json/goes/primary/
- DONKI API base change — ccmc.gsfc.nasa.gov/news/major-updates/
- MSL/RAD cruise doses and shielding — Guo et al. 2015, A&A 577, A58 (aanda.org)
- NASA-STD-3001 radiation limits — NASA OCHMO radiation protection technical brief
- MissionDPT — NTRS 20260001774; ARRT — ORNL publication; CCMC SEP Scoreboard — ccmc.gsfc.nasa.gov/scoreboards/sep
- 2025 Space Apps winners (SpaceGenes+) — nasa.gov announcement, 19 Dec 2025
- Proton stopping power reference values — NIST PSTAR
