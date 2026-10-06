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


def naip(site: Site, grid=None, res: float = NAIP_RES):
    import planetary_computer
    import pystac_client
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT
    from shapely.geometry import box, shape

    g = grid or site.grid()
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
    w = int(round(g.width * g.res / res))
    t = from_origin(g.x0, g.y1, res, res)
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


OVERPASS = "https://overpass-api.de/api/interpreter"


def osm(lon0, lat0, lon1, lat1) -> dict:
    """Port, industrial and terminal outlines from OpenStreetMap, as GeoJSON."""
    import urllib.parse
    import urllib.request
    q = f"""[out:json][timeout:60];
(way["landuse"~"port|industrial"]({lat0},{lon0},{lat1},{lon1});
 relation["landuse"~"port|industrial"]({lat0},{lon0},{lat1},{lon1});
 way["name"~"[Tt]erminal|[Bb]erth|[Ll]og [Yy]ard|[Ll]aydown"]({lat0},{lon0},{lat1},{lon1});
 way["industrial"]({lat0},{lon0},{lat1},{lon1}););
out geom tags;"""
    req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": q}).encode(),
                                 headers={"User-Agent": "sentinel-stockpile (github.com/bdgroves/sentinel-stockpile)"})
    j = _retry(lambda: json.loads(urllib.request.urlopen(req, timeout=120).read()))
    feats = []
    for el in j.get("elements", []):
        geom = el.get("geometry")
        if el["type"] == "way" and geom and len(geom) >= 4:
            ring = [[p["lon"], p["lat"]] for p in geom]
            if ring[0] != ring[-1]:
                continue
            feats.append({"type": "Feature", "properties": {"osm": f"way/{el['id']}", **el.get("tags", {})},
                          "geometry": {"type": "Polygon", "coordinates": [ring]}})
        elif el["type"] == "relation":
            for m in el.get("members", []):
                if m.get("role") == "outer" and m.get("geometry") and len(m["geometry"]) >= 4:
                    ring = [[p["lon"], p["lat"]] for p in m["geometry"]]
                    if ring[0] == ring[-1]:
                        feats.append({"type": "Feature", "properties": {"osm": f"relation/{el['id']}", **el.get("tags", {})},
                                      "geometry": {"type": "Polygon", "coordinates": [ring]}})
    return {"type": "FeatureCollection", "features": feats}


def scout(name: str, lat: float, lon: float, half: float = 2500.0, res: float = 2.5):
    """A wide NAIP view and the OSM outlines around a point, for drawing AOIs."""
    from PIL import Image
    s = Site(id=name, name=name, commodity="lumber", latitude=lat, longitude=lon, buffer_meters=half)
    g = s.grid()
    img, dates, year = naip(s, g, res)
    out = ROOT / "docs" / "validation" / "scout"
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.moveaxis(img, 0, -1)).save(out / f"{name}.jpg", quality=85)
    lon0, lat0, lon1, lat1 = g.lonlat_bounds()
    fc = osm(lon0, lat0, lon1, lat1)
    (out / f"{name}.geojson").write_text(json.dumps(fc))
    (out / f"{name}.json").write_text(json.dumps({"lat": lat, "lon": lon, "half": half, "res": res,
                                                  "crs": g.crs, "bounds": g.bounds, "naip": dates}))
    print(f"scout {name}: NAIP {year}, {len(fc['features'])} OSM outlines")
