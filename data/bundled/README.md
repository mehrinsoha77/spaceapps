# Bundled data

Read-only copy of the historical storm data, committed so a deployment (for example
on Vercel) can replay the storms without contacting NASA during a demo.

Fill it while online, then commit it:

```bash
python scripts/fetch_data.py --bundle
git add data/bundled && git commit -m "Bundle storm data"
```

- `omni/omni2_YYYY_protons.npz`: NASA SPDF OMNI2 hourly proton fluxes (words 43–48),
  one file per year, compacted from `omni2_YYYY.dat`.
- `events/<storm>/donki_*.json`: NASA DONKI flare, CME and SEP records for each storm.

If this folder holds no data, SHELTER downloads the same files from NASA on first
use and caches them (in `/tmp` on Vercel).
