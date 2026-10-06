"""
One clear midsummer scene per year, side by side, with that day's piles
outlined: the at-a-glance version of the year-over-year chart.

    python tools/summers.py --site vancouver_wind
writes docs/charts/<site>_summers.jpg (run after `python -m stockpile rebuild`)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stockpile.sites import ROOT, load  # noqa: E402


def pick(scenes, year, months=(7, 8)):
    """The clearest scene in July-August of a year, nearest mid-July-August
    among the clearest few, so every panel shows the same season."""
    c = [s for s in scenes if s["date"].startswith(str(year)) and int(s["date"][5:7]) in months]
    if not c:
        return None
    c.sort(key=lambda s: (s.get("cloud_context") or 0))
    best = c[: max(3, len(c) // 3)]
    return min(best, key=lambda s: abs(int(s["date"][5:7]) * 31 + int(s["date"][8:]) - 8 * 31))


def main():
    from PIL import Image, ImageDraw, ImageFont
    from pyproj import Transformer
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--scale", type=int, default=4)
    a = ap.parse_args()
    site = load(a.site)
    d = ROOT / "docs" / "data" / site.id
    S = json.loads((d / "series.json").read_text())
    g = S["grid"]
    x0, y0, x1, y1 = g["bounds"]
    res = g["res"]
    to = Transformer.from_crs("EPSG:4326", g["crs"], always_xy=True)
    years = sorted({int(s["date"][:4]) for s in S["scenes"]})
    panels = []
    for y in years:
        s = pick(S["scenes"], y)
        if not s:
            continue
        stem = s["date"].replace("-", "")
        im = Image.open(d / "thumbs" / f"{stem}.jpg").convert("RGB")
        im = im.resize((im.width * a.scale, im.height * a.scale), Image.LANCZOS)
        dr = ImageDraw.Draw(im)

        def px(lon, lat):
            X, Y = to.transform(lon, lat)
            return ((X - x0) / res * a.scale, (y1 - Y) / res * a.scale)

        for geom in [S["aoi"]]:
            polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
            for p in polys:
                dr.line([px(*c) for c in p[0]], fill=(235, 235, 235), width=2)
        fc = json.loads((d / "objects" / f"{stem}.geojson").read_text())
        for f in fc["features"]:
            if f["properties"].get("persistent"):
                continue
            gm = f["geometry"]
            polys = gm["coordinates"] if gm["type"] == "MultiPolygon" else [gm["coordinates"]]
            for p in polys:
                dr.line([px(*c) for c in p[0]], fill=(255, 176, 32), width=3)
        panels.append((im, s))
    if not panels:
        raise SystemExit("no summer scenes")
    w, h = panels[0][0].size
    pad, top = 12, 64
    out = Image.new("RGB", (len(panels) * (w + pad) + pad, h + top + pad), (14, 17, 22))
    dr = ImageDraw.Draw(out)
    try:
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 26)
        small = ImageFont.truetype("DejaVuSans.ttf", 18)
    except OSError:
        big = small = ImageFont.load_default()
    for i, (im, s) in enumerate(panels):
        x = pad + i * (w + pad)
        out.paste(im, (x, top))
        dr.text((x, 8), s["date"][:4], fill=(240, 240, 240), font=big)
        dr.text((x, 38), f"{s['date']} · {s['active_ha']:.1f} ha", fill=(255, 176, 32), font=small)
    dst = ROOT / "docs" / "charts" / f"{site.id}_summers.jpg"
    out.save(dst, quality=88)
    print(f"wrote {dst.relative_to(ROOT)}: " + ", ".join(f"{s['date']} {s['active_ha']} ha" for _, s in panels))


if __name__ == "__main__":
    main()
