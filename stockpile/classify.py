"""
Spectral classification of each pixel, then clean-up into objects.

Classes: 1 water, 2 vegetation, 3 stockpile, 4 ground (and 0 no data).

The rules are the same family as v1 (NDWI for water, NDVI for vegetation,
then a bare-soil index and a brightness window for stockpile material), with
the thresholds per commodity in sites/commodities.json. A commodity's
thresholds carry the reflectance scale they were tuned on: 'legacy' rules are
applied to reflectance with Sentinel-2's +0.1 offset put back, so v1's tuning
reproduces exactly; 'true' rules apply to surface reflectance.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

WATER, VEG, PILE, GROUND = 1, 2, 3, 4
NAMES = {0: "nodata", 1: "water", 2: "vegetation", 3: "stockpile", 4: "ground"}
LEGACY_OFFSET = 0.1


def _nd(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        r = (a - b) / (a + b)
    return np.where(np.isfinite(r), r, 0.0).astype(np.float32)


def reflectance(stack: np.ndarray):
    """int16 x 10000 stack -> dict of float32 reflectance, and a valid mask."""
    valid = (stack != -32768).all(axis=0)
    r = np.where(valid, stack.astype(np.float32) / 10000.0, np.nan)
    return dict(zip(["blue", "green", "red", "nir", "swir1", "swir2"], r)), valid


def indices(b: dict, shift: float = 0.0) -> dict:
    b = {k: v + shift for k, v in b.items()}
    return {
        "ndvi": _nd(b["nir"], b["red"]),
        "ndwi": _nd(b["green"], b["nir"]),
        "bsi": _nd(b["swir1"] + b["red"], b["nir"] + b["blue"]),
        "brightness": ((b["red"] + b["green"] + b["blue"]) / 3.0).astype(np.float32),
    }


def classify(stack: np.ndarray, rules: dict) -> np.ndarray:
    b, valid = reflectance(stack)
    ix = indices(b, LEGACY_OFFSET if rules.get("scale") == "legacy" else 0.0)
    out = np.full(valid.shape, GROUND, dtype=np.uint8)
    water = ix["ndwi"] > rules["water_ndwi"]
    veg = ~water & (ix["ndvi"] > rules["veg_ndvi"])
    pile = (~water & ~veg & (ix["bsi"] > rules["bsi_min"])
            & (ix["brightness"] > rules["brightness_min"]) & (ix["brightness"] < rules["brightness_max"]))
    out[water] = WATER
    out[veg] = VEG
    out[pile] = PILE
    out[~valid] = 0
    return out


def clean(pile: np.ndarray, min_px: int = 3, fill_px: int = 2) -> np.ndarray:
    """Drop specks smaller than min_px pixels and fill pinholes up to fill_px
    inside piles. 8-connected, so a diagonal row of pixels is one object."""
    eight = np.ones((3, 3), bool)
    lab, n = ndimage.label(pile, structure=eight)
    if n:
        sizes = ndimage.sum(pile, lab, index=np.arange(1, n + 1))
        keep = np.zeros(n + 1, bool)
        keep[1:] = sizes >= min_px
        pile = keep[lab]
    if fill_px > 0:
        holes = ndimage.binary_fill_holes(pile) & ~pile
        hl, hn = ndimage.label(holes)
        if hn:
            hs = ndimage.sum(holes, hl, index=np.arange(1, hn + 1))
            small = np.zeros(hn + 1, bool)
            small[1:] = hs <= fill_px
            pile = pile | small[hl]
    return pile


def objects(pile: np.ndarray, grid, smooth_m: float = 6.0, min_area_m2: float = 0.0) -> list[dict]:
    """Connected piles as GeoJSON features (lon/lat). Area comes from the
    pixels; the outline is the pixel boundary rounded off by `smooth_m`
    (a buffer out and back in), so the map shows piles, not staircases."""
    from rasterio.features import shapes
    from rasterio.warp import transform_geom
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union

    eight = np.ones((3, 3), bool)
    lab, n = ndimage.label(pile, structure=eight)
    if not n:
        return []
    px = grid.res * grid.res
    feats = []
    sizes = ndimage.sum(pile, lab, index=np.arange(1, n + 1))
    for geom, val in shapes(lab.astype(np.int32), mask=pile, transform=grid.transform, connectivity=8):
        feats.append((int(val), shape(geom)))
    by = {}
    for v, g in feats:
        by.setdefault(v, []).append(g)
    out = []
    for v, gs in by.items():
        area = float(sizes[v - 1] * px)
        if area < min_area_m2:
            continue
        poly = unary_union(gs)
        smooth = poly.buffer(smooth_m, join_style=1).buffer(-smooth_m, join_style=1).simplify(1.5)
        if smooth.is_empty:
            smooth = poly
        c = poly.centroid
        out.append({"type": "Feature",
                    "properties": {"id": v, "area_m2": round(area), "px": int(sizes[v - 1])},
                    "geometry": transform_geom(grid.crs, "EPSG:4326", mapping(smooth), precision=6),
                    "_c": (c.x, c.y)})
    out.sort(key=lambda f: -f["properties"]["area_m2"])
    for i, f in enumerate(out, 1):
        f["properties"]["rank"] = i
        f.pop("_c")
    return out
