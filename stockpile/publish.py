"""Site manifest for the dashboard, and the charts the README shows."""
from __future__ import annotations

import json
from datetime import date

from .sites import ROOT, all_ids

INK, MUTED, GRID = "#1f2328", "#6a737d", "#e3e1dc"
YEARS = {2023: "#b8b0a4", 2024: "#7a9cb8", 2025: "#2e7aa6", 2026: "#c8602e", 2027: "#6b4c9a"}


def manifest() -> list[dict]:
    out = []
    for sid in all_ids():
        p = ROOT / "docs" / "data" / sid / "series.json"
        if not p.exists():
            continue
        s = json.loads(p.read_text())
        rows = s["scenes"]
        last = rows[-1]
        d = date.fromisoformat(last["date"])
        wk = str(d.isocalendar()[1])
        year_ago = [r for r in rows if abs((date.fromisoformat(r["date"]) - d.replace(year=d.year - 1)).days) <= 10]
        out.append({
            "id": sid, "name": s["site"]["name"], "commodity": s["site"]["commodity"],
            "latitude": s["site"]["latitude"], "longitude": s["site"]["longitude"],
            "first": rows[0]["date"], "last": last["date"], "n": len(rows),
            "latest_active_ha": last["smooth_active_ha"], "latest_area_ha": last["smooth_ha"],
            "norm_active_ha": s["norm_active_by_week"].get(wk),
            "year_ago_active_ha": (sorted(r["smooth_active_ha"] for r in year_ago)[len(year_ago) // 2]
                                   if year_ago else None),
            "spark": [[r["date"], r["smooth_active_ha"]] for r in rows][-60:],
        })
    (ROOT / "docs" / "data" / "sites.json").write_text(json.dumps(
        {"updated": date.today().isoformat(), "sites": out}, separators=(",", ":")))
    return out


def charts():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    out = ROOT / "docs" / "charts"
    out.mkdir(parents=True, exist_ok=True)
    for sid in all_ids():
        p = ROOT / "docs" / "data" / sid / "series.json"
        if not p.exists():
            continue
        s = json.loads(p.read_text())
        rows = s["scenes"]
        dts = [date.fromisoformat(r["date"]) for r in rows]

        # 1. the whole record
        fig, ax = plt.subplots(figsize=(10, 3.6), dpi=150)
        ax.scatter(dts, [r["active_ha"] for r in rows], s=10, color="#b8b0a4", zorder=2, label="each clear scene")
        ax.plot(dts, [r["smooth_active_ha"] for r in rows], color="#2e7aa6", lw=2, zorder=3, label="3-week running median")
        ax.set_ylabel("active stockpile (ha)", color=INK)
        ax.set_title(s["site"]["name"], loc="left", fontsize=12, color=INK)
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.legend(frameon=False, fontsize=8, loc="upper left")
        fig.tight_layout()
        fig.savefig(out / f"{sid}.png")
        plt.close(fig)

        # 2. year over year, on a shared calendar
        fig, ax = plt.subplots(figsize=(10, 3.6), dpi=150)
        for y in sorted({d.year for d in dts}):
            sel = [(d, r) for d, r in zip(dts, rows) if d.year == y]
            x = [date(2000, d.month, min(d.day, 28)) for d, _ in sel]
            ax.plot(x, [r["smooth_active_ha"] for _, r in sel], color=YEARS.get(y, MUTED), lw=2, label=str(y))
        ax.set_ylabel("active stockpile (ha)", color=INK)
        ax.set_title(f"{s['site']['name']}: year over year", loc="left", fontsize=12, color=INK)
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.legend(frameon=False, fontsize=8, ncol=5, loc="upper left")
        fig.tight_layout()
        fig.savefig(out / f"{sid}_yoy.png")
        plt.close(fig)
