"""
Calibration aid (run locally, after `pixi run stacks`):

    python tools/calibrate.py --site vancouver_wind [--rules '{"brightness_min":0.2}']

For the clear Sentinel-2 scene nearest the site's NAIP photo, it writes
docs/validation/<site>_check.jpg: the 0.6 m NAIP photo with the pixels the
classifier calls stockpile outlined, and the Sentinel scene beside it. It also
prints the index values inside the yard so thresholds can be set from data.
Try rule changes with --rules (a JSON patch on the commodity's rules) before
writing them into sites/commodities.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stockpile import classify as C  # noqa: E402
from stockpile.fetch import load_stack, stacks_dir  # noqa: E402
from stockpile.sites import ROOT, commodities, load  # noqa: E402


def nearest_stack(site_id, day):
    best = None
    for f in stacks_dir(site_id).glob("*.npz"):
        d = date(int(f.stem[:4]), int(f.stem[4:6]), int(f.stem[6:]))
        k = abs((d - day).days)
        if best is None or k < best[0]:
            best = (k, f, d)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--rules", default="{}")
    ap.add_argument("--date", help="Sentinel date to use (default: nearest the NAIP photo)")
    a = ap.parse_args()
    from PIL import Image, ImageDraw
    site = load(a.site)
    rules = {**commodities()[site.commodity], **json.loads(a.rules)}
    meta = json.loads((ROOT / "docs/validation" / f"{site.id}.json").read_text())
    naip_day = date.fromisoformat(meta["naip_dates"][0])
    k, f, d = nearest_stack(site.id, date.fromisoformat(a.date) if a.date else naip_day)
    stack, _ = load_stack(f)
    aoi = site.aoi_mask()
    cls = C.classify(stack, rules)
    green = C.seasonal_green([C.ndvi(load_stack(g)[0]) for g in sorted(stacks_dir(site.id).glob("*.npz"))], rules)
    pile = C.clean((cls == C.PILE) & aoi & ~green, rules.get("min_object_px", 3), rules.get("fill_holes_px", 2))
    b, valid = C.reflectance(stack)
    ix = C.indices(b, C.LEGACY_OFFSET if rules.get("scale") == "legacy" else 0.0)
    print(f"{site.id}: Sentinel {d} ({k} days from NAIP {naip_day}); rules scale={rules.get('scale')}")
    print(f"  stockpile {pile.sum() / 100:.1f} ha of {aoi.sum() / 100:.1f} ha yard ({pile.sum() / aoi.sum():.0%})")
    for name in ("brightness", "warmth", "saturation", "swir1", "bsi", "ndvi", "ndwi"):
        v = ix[name][aoi & valid]
        q = np.percentile(v, [5, 25, 50, 75, 95])
        print(f"  {name:<10} yard p5 {q[0]:6.3f}  p25 {q[1]:6.3f}  p50 {q[2]:6.3f}  p75 {q[3]:6.3f}  p95 {q[4]:6.3f}")
    # NAIP with the 10 m stockpile pixels outlined, plus the Sentinel scene
    naip = Image.open(ROOT / "docs/validation" / f"{site.id}_naip.jpg").convert("RGB")
    s = naip.width / pile.shape[1]
    ov = Image.new("RGBA", naip.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(ov)
    for r, c in zip(*np.nonzero(pile)):
        dr.rectangle([c * s, r * s, (c + 1) * s - 1, (r + 1) * s - 1], outline=(255, 170, 0, 255), width=2)
    edge = aoi & ~np.pad(aoi, 1)[2:, 1:-1] | aoi & ~np.pad(aoi, 1)[:-2, 1:-1] | aoi & ~np.pad(aoi, 1)[1:-1, 2:] | aoi & ~np.pad(aoi, 1)[1:-1, :-2]
    for r, c in zip(*np.nonzero(edge)):
        dr.rectangle([c * s, r * s, (c + 1) * s - 1, (r + 1) * s - 1], fill=(255, 255, 255, 90))
    left = Image.alpha_composite(naip.convert("RGBA"), ov).convert("RGB")
    rgb = np.stack([stack[2], stack[1], stack[0]], -1).astype(np.float32) / 10000
    sen = Image.fromarray((np.clip(np.nan_to_num(rgb) * 3.2, 0, 1) ** 0.8 * 255).astype(np.uint8)).resize(naip.size, Image.NEAREST)
    out = Image.new("RGB", (naip.width * 2 + 10, naip.height), "white")
    out.paste(left, (0, 0))
    out.paste(sen, (naip.width + 10, 0))
    dst = ROOT / "docs/validation" / f"{site.id}_check.jpg"
    out.resize((out.width // 2, out.height // 2)).save(dst, quality=85)
    print(f"  wrote {dst.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
