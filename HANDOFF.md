# Handoff: Sentinel Stockpile v3 (6 October 2026)

## State
- v3 is live in `main`: package `stockpile/`, sites in `sites/`, rules in `sites/commodities.json`, dashboard in `docs/`.
- `monitor.yml` runs Mon + Thu 15:23 UTC. Manually dispatched on 2026-10-06 with the v3 code: all jobs green, one publish commit.
- Band stacks (229 MB) live on the single-commit `stacks` branch. `pixi run stacks` pulls them for local work; reclassifying locally (`python -m stockpile rebuild --site X`) takes a minute or two per site.
- Blog: brooksgroves.com/blog/sentinel-stockpile-revisited-post.html (fact-checked by a separate agent). The April post carries an update note.

## To do
- **GitHub Pages**: Brooks needs to enable Settings → Pages → Deploy from branch → `main` / `/docs`, so the dashboard serves at brooksgroves.com/sentinel-stockpile/ (the Pages API is blocked from the cloud session).
- Confirm the first *scheduled* run (Thursday 2026-10-08) commits.
- Ideas: Kalama grain, Tacoma auto lots, Sentinel-1 radar for winter, shipping data to explain the Terminal 5 decline.

## Calibration notes (true reflectance)
- **Lumber:** warmth (R−B)/(R+B) > 0.25, brightness 0.09–0.45, NDVI < 0.4, plus a seasonal-green mask (90th-percentile NDVI > 0.55) because summer-dry grass is log-coloured.
  - A SWIR1 > 0.28 test was tried and dropped: wet logs lose SWIR and summer scenes after rain dropped to ~1 ha.
- **Wind:** brightness > 0.2, warmth < 0.1. Blades have NDWI ≈ +0.02–0.05, so water also needs NIR < 0.15.
- **Containers:** warmth > 0.2, brightness 0.04–0.3. Blue and white boxes are missed. Persistent subtraction is off.
- **Snow:** NDSI > 0.4 is a class. A scene with more than 20% of the yard as snow is set aside (2024-01-15).
- **Haze:** a scene is set aside when the yard's median blue is more than 1.5× the site's usual (2024-09-06, 2026-08-04 …).
- **Longview port** was retargeted to wind components. Its outline holds blade racks and steel; the logs are at Weyerhaeuser.
- **Thumbnails** are always rewritten. Stale ones from the old grids had survived because dates matched.
- **Tools:**
  - `tools/calibrate.py --site X --rules '{...}'` prints yard index percentiles and draws the overlay on NAIP.
  - `tools/summers.py --site X` renders one midsummer scene per year.

## Findings (June–September medians, active ha)
| Site | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|
| Terminal 5 | 3.64 | 1.19 | 0.27 | 0.07 |
| Longview | 5.89 | 4.31 | 3.25 | 2.67 |
| Weyerhaeuser | 33.1 | 34.1 | 31.7 | 25.0 |
| Tacoma | 7.4 | 12.8 | 11.4 | 9.1 |

The wind numbers are a proxy for bright white cargo, and no cause is claimed.
