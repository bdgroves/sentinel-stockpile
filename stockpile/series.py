"""
Turn a site's cached scenes into its time series and the files the dashboard
reads.

For every accepted scene: classify, clean into objects, and measure
  area_ha        all stockpile in the yard
  persistent_ha  the part that is 'stockpile' on nearly every clear date
                 (roofs, slabs, a stack that never moves): reported apart so
                 it doesn't masquerade as activity
  active_ha      area_ha - persistent_ha: what comes and goes
  n_objects, largest_ha

Then a smoothed line (centred running median over 21 days, valid scenes
only), and a seasonal norm: the median for each week of the year across all
earlier years, so a date can be compared with what is usual for it.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from scipy import ndimage

from . import classify as C
from .fetch import load_catalog, load_stack, stacks_dir
from .sites import ROOT, Site, commodities

PERSIST_FRAC = 0.9        # stockpile on at least this share of clear scenes ...
PERSIST_MIN_SCENES = 20   # ... out of at least this many
SMOOTH_DAYS = 21


def web_dir(site_id: str) -> Path:
    return ROOT / "docs" / "data" / site_id


def thumb(stack: np.ndarray, path: Path, gain: float = 3.2):
    """True-colour JPEG at the native 10 m (one pixel per Sentinel-2 pixel)."""
    from PIL import Image
    rgb = np.stack([stack[2], stack[1], stack[0]], axis=-1).astype(np.float32) / 10000.0
    rgb = np.clip(np.nan_to_num(rgb) * gain, 0, 1) ** (1 / 1.25)
    Image.fromarray((rgb * 255 + 0.5).astype(np.uint8)).save(path, quality=88)


def running_median(days: np.ndarray, vals: np.ndarray, window: int) -> np.ndarray:
    out = np.empty_like(vals, dtype=float)
    h = window / 2
    for i, d in enumerate(days):
        m = np.abs(days - d) <= h
        out[i] = np.median(vals[m])
    return out


def build(site: Site, write_objects: bool = True) -> dict:
    rules = commodities()[site.commodity]
    grid = site.grid()
    aoi = site.aoi_mask()
    px_ha = grid.res * grid.res / 1e4
    catalog = {s["date"]: s for s in load_catalog(site.id)}
    files = sorted(stacks_dir(site.id).glob("*.npz"))
    out_dir = web_dir(site.id)
    (out_dir / "objects").mkdir(parents=True, exist_ok=True)
    (out_dir / "thumbs").mkdir(parents=True, exist_ok=True)

    # pass 1: classify and clean every cached scene
    scenes, piles = [], []
    for f in files:
        stack, meta = load_stack(f)
        day = f"{f.stem[:4]}-{f.stem[4:6]}-{f.stem[6:]}"
        cls = C.classify(stack, rules)
        pile = C.clean((cls == C.PILE) & aoi, rules.get("min_object_px", 3), rules.get("fill_holes_px", 2))
        valid = (cls > 0) & aoi
        scenes.append({"date": day, "stack": f, "cls": cls, "valid": valid})
        piles.append(pile)
        if write_objects:
            tp = out_dir / "thumbs" / f"{f.stem}.jpg"
            if not tp.exists():
                thumb(stack, tp)
    if not scenes:
        return {}
    P = np.stack(piles)
    n_clear = len(scenes)
    freq = P.mean(axis=0)
    persistent = (freq >= PERSIST_FRAC) if n_clear >= PERSIST_MIN_SCENES else np.zeros_like(freq, bool)

    # pass 2: measure
    rows = []
    for s, pile in zip(scenes, piles):
        cls = s["cls"]
        feats = C.objects(pile, grid)
        # tag objects that are mostly always-on ground (roofs, slabs) so the
        # pile count and the largest pile describe what actually moves
        if persistent.any():
            lab, _ = ndimage.label(pile, structure=np.ones((3, 3), bool))
            for f_ in feats:
                m = lab == f_["properties"]["id"]
                f_["properties"]["persistent"] = bool((m & persistent).sum() > 0.5 * m.sum())
        moving = [f_ for f_ in feats if not f_["properties"].get("persistent")]
        a = pile.sum() * px_ha
        pers = (pile & persistent).sum() * px_ha
        rows.append({
            "date": s["date"],
            "area_ha": round(float(a), 3),
            "active_ha": round(float(a - pers), 3),
            "persistent_ha": round(float(pers), 3),
            "fraction": round(float(pile.sum() / max(1, aoi.sum())), 4),
            "n_objects": len(moving),
            "largest_ha": round(moving[0]["properties"]["area_m2"] / 1e4, 3) if moving else 0.0,
            "water_ha": round(float(((cls == C.WATER) & aoi).sum() * px_ha), 2),
            "veg_ha": round(float(((cls == C.VEG) & aoi).sum() * px_ha), 2),
            "cloud_context": catalog.get(s["date"], {}).get("cloud_context"),
        })
        if write_objects:
            (out_dir / "objects" / f"{s['stack'].stem}.geojson").write_text(json.dumps(
                {"type": "FeatureCollection", "features": feats}, separators=(",", ":")))

    days = np.array([(date.fromisoformat(r["date"]) - date(2000, 1, 1)).days for r in rows], float)
    area = np.array([r["area_ha"] for r in rows])
    active = np.array([r["active_ha"] for r in rows])
    sm = running_median(days, area, SMOOTH_DAYS)
    sma = running_median(days, active, SMOOTH_DAYS)
    for r, a, b in zip(rows, sm, sma):
        r["smooth_ha"] = round(float(a), 3)
        r["smooth_active_ha"] = round(float(b), 3)

    # seasonal norm by ISO week, from every year before the latest one
    latest_year = date.fromisoformat(rows[-1]["date"]).year
    weeks: dict[int, list] = {}
    for r in rows:
        d = date.fromisoformat(r["date"])
        if d.year < latest_year:
            weeks.setdefault(d.isocalendar()[1], []).append(r["active_ha"])
    norm = {str(w): round(float(np.median(v)), 3) for w, v in sorted(weeks.items()) if len(v) >= 2}

    # where the persistent area is, as an outline for the map
    pers_feats = C.objects(persistent, grid) if persistent.any() else []

    rejected = [s for s in catalog.values() if s.get("status") != "ok"]
    series = {
        "site": {k: getattr(site, k) for k in ("id", "name", "commodity", "latitude", "longitude",
                                                 "buffer_meters", "description", "notes")},
        "aoi": site.aoi_geojson(),
        "grid": {"crs": grid.crs, "bounds": grid.bounds, "lonlat_bounds": grid.lonlat_bounds(),
                 "res": grid.res, "size": [grid.width, grid.height]},
        "rules": rules,
        "persistent": {"type": "FeatureCollection", "features": pers_feats,
                       "rule": f"stockpile on >= {PERSIST_FRAC:.0%} of {n_clear} clear scenes",
                       "area_ha": round(float(persistent.sum() * px_ha), 3)},
        "scenes": rows,
        "norm_active_by_week": norm,
        "looked_at": len(catalog),
        "rejected": {k: sum(1 for s in rejected if s.get("status") == k) for k in ("cloudy", "nodata")},
        "updated": date.today().isoformat(),
        "version": 2,
    }
    (out_dir / "series.json").write_text(json.dumps(series, separators=(",", ":")))
    # a flat CSV for anyone who just wants the numbers
    cols = ["date", "area_ha", "active_ha", "persistent_ha", "smooth_ha", "fraction", "n_objects",
            "largest_ha", "cloud_context"]
    lines = [",".join(cols)] + [",".join("" if r.get(c) is None else str(r[c]) for c in cols) for r in rows]
    (ROOT / "data" / site.id).mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / site.id / "time_series.csv").write_text("\n".join(lines) + "\n")
    print(f"{site.id}: {len(rows)} clear scenes ({rows[0]['date']} .. {rows[-1]['date']}), "
          f"persistent {series['persistent']['area_ha']} ha, rejected {series['rejected']}", flush=True)
    return series
