"""
Find Sentinel-2 L2A scenes over a site (Microsoft Planetary Computer), judge
them for cloud, and cache the six bands we use as a compact stack on the
site's fixed grid.

What changed from v1:
  * reflectance has Sentinel-2's +1000 offset removed (processing baseline
    04.00 and later, which is every scene since January 2022);
  * every scene is warped onto the same 10 m UTM grid, so pixels line up;
  * clouds are judged with the scene classification layer (SCL) over a 3 km
    window around the site, not the tile-wide cloud percentage. Bright piles
    (white turbine blades, tarps) are sometimes flagged as cloud by SCL, so
    the yard itself is only checked for high-confidence cloud and cirrus;
  * no 50-scene cap: the search pages through everything.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import numpy as np

from .sites import ROOT, Site

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
BANDS10 = ["B02", "B03", "B04", "B08"]
BANDS20 = ["B11", "B12"]
BANDS = BANDS10 + BANDS20
# SCL classes
SCL_NODATA, SCL_SATURATED, SCL_SHADOW, SCL_CLOUD_MED, SCL_CLOUD_HIGH, SCL_CIRRUS = 0, 1, 3, 8, 9, 10

# Scene acceptance (fractions)
MAX_CONTEXT_CLOUD = 0.10      # cloud + shadow in the 3 km window
MAX_AOI_CLOUD = 0.02          # high-confidence cloud, cirrus or shadow over the yard
MAX_AOI_NODATA = 0.01


def stacks_dir(site_id: str) -> Path:
    return ROOT / "stacks" / site_id


def catalog_path(site_id: str) -> Path:
    return ROOT / "data" / site_id / "scenes.json"


def load_catalog(site_id: str) -> list[dict]:
    p = catalog_path(site_id)
    return json.loads(p.read_text()) if p.exists() else []


def save_catalog(site_id: str, scenes: list[dict]):
    p = catalog_path(site_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    scenes = sorted({s["date"]: s for s in scenes}.values(), key=lambda s: s["date"])
    p.write_text(json.dumps(scenes, indent=1))


def _retry(fn, tries=5, wait=5):
    for k in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - network: retry anything
            if k == tries - 1:
                raise
            print(f"    retry {k + 1}: {e.__class__.__name__}: {str(e)[:120]}", flush=True)
            time.sleep(wait * (k + 1))


def search(site: Site, start: str, end: str, max_tile_cloud: float = 80.0):
    """All L2A items over the site between start and end, one per day: the
    one whose footprint covers the yard, with the least cloud."""
    import pystac_client
    from shapely.geometry import box, shape

    lon0, lat0, lon1, lat1 = site.grid().lonlat_bounds()
    yard = box(lon0, lat0, lon1, lat1)
    cat = _retry(lambda: pystac_client.Client.open(STAC))
    items = _retry(lambda: list(cat.search(
        collections=["sentinel-2-l2a"], bbox=site.context_grid().lonlat_bounds(),
        datetime=f"{start}/{end}", query={"eo:cloud_cover": {"lt": max_tile_cloud}}, limit=100).items()))
    by_day: dict[str, object] = {}
    for it in items:
        if not shape(it.geometry).contains(yard):
            continue
        d = it.datetime.date().isoformat()
        cc = it.properties.get("eo:cloud_cover", 100)
        if d not in by_day or cc < by_day[d].properties.get("eo:cloud_cover", 100):
            by_day[d] = it
    return [by_day[d] for d in sorted(by_day)]


def _read(href, grid, resampling, dtype="uint16"):
    import rasterio
    from rasterio.vrt import WarpedVRT
    with rasterio.open(href) as src, WarpedVRT(src, crs=grid.crs, transform=grid.transform,
                                                width=grid.width, height=grid.height,
                                                resampling=resampling, nodata=0) as vrt:
        return vrt.read(1).astype(dtype)


def offset_for(item) -> int:
    """Sentinel-2 L2A adds 1000 to every reflectance from processing baseline
    04.00 (25 January 2022) on; earlier products have no offset."""
    try:
        return 1000 if float(item.properties.get("s2:processing_baseline", "0")) >= 4.0 else 0
    except ValueError:
        return 1000 if item.datetime.date() >= date(2022, 1, 25) else 0


def judge(site: Site, item) -> dict:
    """Cloud and coverage statistics from the scene classification layer."""
    from rasterio.enums import Resampling
    ctx = _retry(lambda: _read(item.assets["SCL"].href, site.context_grid(), Resampling.nearest, "uint8"))
    g = site.grid()
    yard = _retry(lambda: _read(item.assets["SCL"].href, g.__class__(g.crs, g.x0, g.y1, 20.0,
                                                                        g.width // 2, g.height // 2),
                                Resampling.nearest, "uint8"))
    valid_ctx = ctx != SCL_NODATA
    cloudy_ctx = np.isin(ctx, [SCL_SHADOW, SCL_CLOUD_MED, SCL_CLOUD_HIGH, SCL_CIRRUS])
    cloudy_yard = np.isin(yard, [SCL_SHADOW, SCL_CLOUD_HIGH, SCL_CIRRUS])
    rec = {
        "cloud_context": round(float(cloudy_ctx[valid_ctx].mean()) if valid_ctx.any() else 1.0, 4),
        "cloud_aoi": round(float(cloudy_yard.mean()), 4),
        "nodata_aoi": round(float((yard == SCL_NODATA).mean()), 4),
    }
    if rec["nodata_aoi"] > MAX_AOI_NODATA:
        rec["status"] = "nodata"
    elif rec["cloud_context"] > MAX_CONTEXT_CLOUD or rec["cloud_aoi"] > MAX_AOI_CLOUD:
        rec["status"] = "cloudy"
    else:
        rec["status"] = "ok"
    return rec


def fetch_stack(site: Site, item) -> np.ndarray:
    """(6, H, W) int16 surface reflectance x 10000 on the site grid, offset
    removed; -32768 where there is no data."""
    from rasterio.enums import Resampling
    g = site.grid()
    off = offset_for(item)
    out = np.empty((len(BANDS), g.height, g.width), dtype=np.int16)
    for i, b in enumerate(BANDS):
        rs = Resampling.nearest if b in BANDS10 else Resampling.bilinear
        dn = _retry(lambda: _read(item.assets[b].href, g, rs)).astype(np.int32)
        refl = dn - off
        refl[dn == 0] = -32768
        out[i] = np.clip(refl, -32768, 32767)
    return out


def save_stack(site_id: str, day: str, stack: np.ndarray, meta: dict):
    d = stacks_dir(site_id)
    d.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(d / f"{day.replace('-', '')}.npz", bands=stack, meta=json.dumps(meta))


def load_stack(path: Path) -> tuple[np.ndarray, dict]:
    z = np.load(path)
    return z["bands"], json.loads(str(z["meta"]))


def update(site: Site, start: str, end: str) -> list[dict]:
    """Fetch every new acceptable scene between start and end. Scenes already
    in the catalog are skipped, so this is safe to rerun."""
    catalog = load_catalog(site.id)
    seen = {s["date"] for s in catalog}
    items = search(site, start, end)
    new = [it for it in items if it.datetime.date().isoformat() not in seen]
    print(f"{site.id}: {len(items)} days with imagery {start}..{end}, {len(new)} new", flush=True)
    import planetary_computer
    for it in new:
        day = it.datetime.date().isoformat()
        it = planetary_computer.sign(it)        # signed links expire; sign just before use
        rec = {"date": day, "id": it.id, "tile_cloud": it.properties.get("eo:cloud_cover"),
               "baseline": it.properties.get("s2:processing_baseline"), "offset": offset_for(it)}
        try:
            rec.update(judge(site, it))
            if rec["status"] == "ok":
                stack = fetch_stack(site, it)
                if (stack[0] == -32768).mean() > MAX_AOI_NODATA:
                    rec["status"] = "nodata"
                else:
                    save_stack(site.id, day, stack, rec)
        except Exception as e:  # noqa: BLE001 - keep going; record the failure, retry next run
            print(f"  {day}: failed ({e.__class__.__name__}: {str(e)[:100]})", flush=True)
            continue
        catalog.append(rec)
        print(f"  {day}: {rec['status']:<6} cloud {rec['cloud_context']:.1%} around, "
              f"{rec['cloud_aoi']:.1%} over the yard", flush=True)
    save_catalog(site.id, catalog)
    return catalog
