"""
Ground truth, or close to it: the USDA NAIP aerial photo (0.6 m) over each
yard, on the site's grid, with the Sentinel-2 stockpile outlines from the
nearest clear date drawn on top. Lets a person check what the classifier
calls a pile.

    python -m stockpile validate --site longview_port
writes docs/validation/<site>.jpg and <site>.json
"""
from __future__ import annotations

import json
from datetime import date

import numpy as np

from .fetch import STAC, _retry
from .sites import ROOT, Site

NAIP_RES = 0.6


def naip(site: Site):
    import planetary_computer
    import pystac_client
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT
    from shapely.geometry import box, shape

    g = site.grid()
    lon0, lat0, lon1, lat1 = g.lonlat_bounds()
    yard = box(lon0, lat0, lon1, lat1)
    cat = _retry(lambda: pystac_client.Client.open(STAC))
    items = _retry(lambda: list(cat.search(collections=["naip"], bbox=[lon0, lat0, lon1, lat1]).items()))
    items = [i for i in items if shape(i.geometry).intersects(yard)]
    if not items:
        raise SystemExit(f"{site.id}: no NAIP")
    year = max(i.datetime.year for i in items)
    items = [planetary_computer.sign(i) for i in items if i.datetime.year == year]
    from rasterio.transform import from_origin
    w = int(round(g.width * g.res / NAIP_RES))
    t = from_origin(g.x0, g.y1, NAIP_RES, NAIP_RES)
    img = np.zeros((3, w, w), np.uint8)
    got = np.zeros((w, w), bool)
    when = []
    for it in items:
        with rasterio.open(it.assets["image"].href) as src, WarpedVRT(
                src, crs=g.crs, transform=t, width=w, height=w, resampling=Resampling.average, nodata=0) as v:
            part = v.read(indexes=[1, 2, 3])
        have = (part.sum(axis=0) > 0) & ~got
        img[:, have] = part[:, have]
        got |= have
        when.append(it.datetime.date().isoformat())
    return img, sorted(set(when)), year


def run(site: Site):
    from PIL import Image
    img, dates, year = naip(site)
    out = ROOT / "docs" / "validation"
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.moveaxis(img, 0, -1)).save(out / f"{site.id}_naip.jpg", quality=85)
    (out / f"{site.id}.json").write_text(json.dumps({"site": site.id, "naip_year": year, "naip_dates": dates,
                                                     "res_m": NAIP_RES, "grid_bounds": site.grid().bounds,
                                                     "made": date.today().isoformat()}))
    print(f"{site.id}: NAIP {year} ({', '.join(dates)})")
