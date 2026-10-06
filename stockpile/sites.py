"""Site registry and the fixed analysis grid each site is measured on."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "sites"
PIXEL = 10.0            # metres: Sentinel-2's visible/NIR resolution
CONTEXT_M = 1500.0      # half-width of the window used to judge clouds


@dataclass
class Grid:
    """A north-up UTM grid; every scene for a site is warped onto the same one,
    so pixel (r, c) is the same patch of ground on every date."""
    crs: str
    x0: float
    y1: float
    res: float
    width: int
    height: int

    @property
    def transform(self):
        from rasterio.transform import from_origin
        return from_origin(self.x0, self.y1, self.res, self.res)

    @property
    def bounds(self):
        return (self.x0, self.y1 - self.height * self.res, self.x0 + self.width * self.res, self.y1)

    def lonlat_bounds(self):
        from rasterio.warp import transform_bounds
        return transform_bounds(self.crs, "EPSG:4326", *self.bounds, densify_pts=21)


@dataclass
class Site:
    id: str
    name: str
    commodity: str
    latitude: float
    longitude: float
    buffer_meters: float
    start: str = "2023-04-01"
    description: str = ""
    notes: str = ""
    aoi: dict | None = None            # optional GeoJSON polygon (lon/lat) of the yard
    extra: dict = field(default_factory=dict)

    @property
    def epsg(self) -> int:
        zone = int((self.longitude + 180) / 6) + 1
        return (32600 if self.latitude >= 0 else 32700) + zone

    def _center_utm(self):
        from pyproj import Transformer
        t = Transformer.from_crs("EPSG:4326", f"EPSG:{self.epsg}", always_xy=True)
        return t.transform(self.longitude, self.latitude)

    def grid(self, half: float | None = None, res: float = PIXEL) -> Grid:
        cx, cy = self._center_utm()
        h = self.buffer_meters if half is None else half
        x0 = math.floor((cx - h) / res) * res
        y1 = math.ceil((cy + h) / res) * res
        n = int(round(2 * h / res))
        return Grid(f"EPSG:{self.epsg}", x0, y1, res, n, n)

    def context_grid(self) -> Grid:
        return self.grid(max(CONTEXT_M, self.buffer_meters + 500), 20.0)

    def aoi_mask(self):
        """Boolean mask of the analysis grid: True inside the yard polygon (or
        everywhere, if the site has none)."""
        import numpy as np
        g = self.grid()
        if not self.aoi:
            return np.ones((g.height, g.width), dtype=bool)
        from rasterio.features import geometry_mask
        from rasterio.warp import transform_geom
        geom = transform_geom("EPSG:4326", g.crs, self.aoi)
        return geometry_mask([geom], out_shape=(g.height, g.width), transform=g.transform, invert=True)

    def aoi_geojson(self) -> dict:
        if self.aoi:
            return self.aoi
        from rasterio.warp import transform_geom
        x0, y0, x1, y1 = self.grid().bounds
        sq = {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}
        return transform_geom(self.grid().crs, "EPSG:4326", sq)


def load(site_id: str) -> Site:
    d = json.loads((SITES / f"{site_id}.json").read_text())
    known = {k: d.pop(k) for k in list(d) if k in Site.__dataclass_fields__}
    return Site(**known, extra=d)


def all_ids() -> list[str]:
    return sorted(p.stem for p in SITES.glob("*.json") if p.stem != "commodities")


def commodities() -> dict:
    return json.loads((SITES / "commodities.json").read_text())
