# 🛰️ Sentinel Stockpile

**Open-source satellite change detection for commodity stockpile monitoring**

Track lumber yards, container terminals, and commodity storage sites using free Sentinel-2 imagery. Measure whether stockpiles are growing, shrinking, or holding steady — no expensive commercial data required.

![Python](https://img.shields.io/badge/python-3.11+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Managed with pixi](https://img.shields.io/badge/managed%20with-pixi-brightgreen)

## What This Does

1. **Fetches free Sentinel-2 imagery** from Microsoft Planetary Computer for any site you define
2. **Runs change detection** comparing imagery across dates using spectral indices and pixel classification
3. **Measures stockpile area** in square meters over time
4. **Generates time series** showing whether a site is accumulating or depleting material
5. **Produces maps and charts** for visual verification

## Proof of Concept Sites (Pacific Northwest)

| Site | Commodity | Coordinates | Why |
|------|-----------|-------------|-----|
| Port of Longview | Lumber | 46.1065, -122.9543 | Largest log export terminal on Columbia River |
| Port of Tacoma | Containers | 47.2690, -122.4130 | Major container terminal, clear stacking patterns |
| Weyerhaeuser Longview | Lumber/Logs | 46.1380, -122.9370 | Massive mill complex visible from space |

## Quick Start

```bash
# Install pixi if you don't have it
curl -fsSL https://pixi.sh/install.sh | bash

# Clone and set up
git clone https://github.com/bdgroves/sentinel-stockpile.git
cd sentinel-stockpile
pixi install

# Run the pipeline for a site
pixi run fetch --site longview_port
pixi run detect --site longview_port
pixi run report --site longview_port

# Or run everything at once
pixi run pipeline --site longview_port
```

## How It Works

### Change Detection Approach

We use a multi-index approach to classify ground cover changes:

1. **NDVI (Normalized Difference Vegetation Index)** — separates vegetation from bare/built surfaces
2. **NDMI (Normalized Difference Moisture Index)** — detects fresh-cut lumber (high moisture) vs. dried/older stock
3. **BSI (Bare Soil Index)** — identifies cleared ground vs. stacked material
4. **Brightness thresholding** — containers and tarped lumber have distinct spectral signatures

For each time step, we classify pixels within the site boundary into:
- **Stockpile** (lumber, containers, material)
- **Ground** (bare, paved)
- **Vegetation** (grass, trees)
- **Water** (if applicable)

Then we compute the **stockpile area delta** between dates.

### Data Pipeline

```
┌─────────────┐    ┌──────────────┐    ┌───────────────┐    ┌────────────┐
│  Planetary   │───▶│  Cloud-free   │───▶│   Spectral    │───▶│  Time      │
│  Computer    │    │  Composite    │    │   Classify    │    │  Series    │
│  STAC API    │    │  (per month)  │    │   & Measure   │    │  & Report  │
└─────────────┘    └──────────────┘    └───────────────┘    └────────────┘
```

## Adding Your Own Sites

Create a JSON file in `config/sites/`:

```json
{
    "site_id": "my_lumber_yard",
    "name": "My Lumber Yard",
    "commodity": "lumber",
    "latitude": 46.1065,
    "longitude": -122.9543,
    "buffer_meters": 500,
    "description": "Description of the site"
}
```

Then run:
```bash
pixi run pipeline --site my_lumber_yard
```

## Project Structure

```
sentinel-stockpile/
├── pixi.toml              # Environment & task definitions
├── config/
│   └── sites/             # Site definition JSON files
├── src/
│   ├── fetch_imagery.py   # Pull Sentinel-2 from Planetary Computer
│   ├── preprocess.py      # Cloud masking, compositing
│   ├── classify.py        # Spectral classification
│   ├── measure.py         # Area calculation & time series
│   ├── report.py          # Generate maps and charts
│   └── pipeline.py        # Orchestrate full workflow
├── output/                # Generated data, charts, maps
├── notebooks/
│   └── explore.ipynb      # Interactive exploration
└── .github/
    └── workflows/
        └── monthly.yml    # Automated monthly monitoring
```

## Roadmap

- [x] Sentinel-2 fetch via Planetary Computer STAC
- [x] Spectral index classification (NDVI, NDMI, BSI)
- [x] Stockpile area measurement & time series
- [x] Site configuration system
- [x] Report generation (maps + charts)
- [ ] Sentinel-1 SAR integration (works through clouds)
- [ ] Container counting via edge detection
- [ ] Multi-site dashboard (static HTML, GitHub Pages)
- [ ] Oil tank shadow analysis (fill level estimation)
- [ ] Grain elevator monitoring
- [ ] GitHub Actions monthly automation
- [ ] Export to GeoJSON for QGIS overlay

## Why Open Source?

Commercial satellite analytics companies charge $50k+/year for commodity monitoring. The underlying data (Sentinel-2) is free. The algorithms aren't secret. This project proves you can build meaningful stockpile intelligence with open tools and open data.

## Tech Stack

- **pixi** — reproducible environment management
- **pystac-client** — search Planetary Computer's STAC catalog
- **planetary-computer** — sign asset URLs for download
- **rasterio** — read/write geospatial rasters
- **numpy** — array math for spectral indices
- **geopandas** — site boundary handling
- **matplotlib** — charts and map visualization
- **shapely** — geometry operations

## License

MIT — use it, fork it, extend it.
