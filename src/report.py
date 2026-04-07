"""
report.py — Generate visual reports: classification maps and time series charts.
"""

import json
import sys
from pathlib import Path

import click
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import numpy as np
import rasterio
from datetime import datetime
from rich.console import Console

console = Console()

# Classification colormap
CLASS_COLORS = {
    0: "#1a1a2e",  # nodata — dark
    1: "#1e81b0",  # water — blue
    2: "#4a7c59",  # vegetation — forest green
    3: "#d4a843",  # stockpile — amber/lumber
    4: "#8c7a6b",  # ground — brown/gray
}
CLASS_LABELS = {0: "No Data", 1: "Water", 2: "Vegetation", 3: "Stockpile", 4: "Ground"}

# Build matplotlib colormap
cmap_colors = [CLASS_COLORS[i] for i in range(5)]
cmap = mcolors.ListedColormap(cmap_colors)
bounds = [-0.5, 0.5, 1.5, 2.5, 3.5, 4.5]
norm = mcolors.BoundaryNorm(bounds, cmap.N)


def plot_classification_map(classified_path: Path, output_path: Path, title: str):
    """Plot a single classification raster as a color-coded map."""
    with rasterio.open(classified_path) as src:
        data = src.read(1)

    fig, ax = plt.subplots(1, 1, figsize=(10, 8))
    im = ax.imshow(data, cmap=cmap, norm=norm, interpolation="nearest")

    # Legend
    patches = [
        plt.Rectangle((0, 0), 1, 1, facecolor=CLASS_COLORS[i])
        for i in [1, 2, 3, 4]
    ]
    labels = [CLASS_LABELS[i] for i in [1, 2, 3, 4]]
    ax.legend(patches, labels, loc="upper right", fontsize=9, framealpha=0.9)

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel("Pixel X")
    ax.set_ylabel("Pixel Y")

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_time_series(time_series: list, output_path: Path, site_name: str):
    """Plot stockpile area over time."""
    dates = [datetime.strptime(e["date"], "%Y-%m-%d") for e in time_series]
    areas_ha = [e["stockpile_ha"] for e in time_series]
    areas_m2 = [e["stockpile_m2"] for e in time_series]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={"height_ratios": [3, 1]})

    # Main area plot
    ax1.fill_between(dates, areas_ha, alpha=0.3, color="#d4a843")
    ax1.plot(dates, areas_ha, "o-", color="#8b6914", linewidth=2, markersize=6)
    ax1.set_ylabel("Stockpile Area (hectares)", fontsize=12)
    ax1.set_title(f"📦 Stockpile Area Over Time — {site_name}", fontsize=14, fontweight="bold")
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    # Delta plot (change between observations)
    if len(areas_m2) > 1:
        deltas = [0] + [areas_m2[i] - areas_m2[i - 1] for i in range(1, len(areas_m2))]
        colors = ["#2e7d32" if d >= 0 else "#c62828" for d in deltas]
        ax2.bar(dates, deltas, width=5, color=colors, alpha=0.7)
        ax2.axhline(y=0, color="black", linewidth=0.5)
        ax2.set_ylabel("Δ Area (m²)", fontsize=11)
        ax2.set_xlabel("Date", fontsize=11)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    console.print(f"  ✓ Time series chart: {output_path}")


def plot_rgb_composite(scene_dir: Path, output_path: Path, title: str):
    """Create a true-color RGB composite from B04, B03, B02."""
    bands = {}
    for band_name in ["B04", "B03", "B02"]:
        band_path = scene_dir / f"{band_name}.tif"
        if not band_path.exists():
            return
        with rasterio.open(band_path) as src:
            bands[band_name] = src.read(1).astype(np.float32) / 3000.0  # stretch

    rgb = np.stack([
        np.clip(bands["B04"], 0, 1),
        np.clip(bands["B03"], 0, 1),
        np.clip(bands["B02"], 0, 1),
    ], axis=-1)

    fig, ax = plt.subplots(1, 1, figsize=(10, 8))
    ax.imshow(rgb)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel("Pixel X")
    ax.set_ylabel("Pixel Y")
    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


@click.command()
@click.option("--site", required=True, help="Site ID")
def main(site: str):
    """Generate visual report for a monitoring site."""
    site_path = Path("config/sites") / f"{site}.json"
    with open(site_path) as f:
        site_config = json.load(f)

    console.print(f"\n[bold]📊 Generating report for {site_config['name']}[/bold]")

    report_dir = Path("output") / site / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    # Classification maps
    classify_dir = Path("output") / site / "classified"
    if classify_dir.exists():
        classified_files = sorted(classify_dir.glob("*_classified.tif"))
        for cf in classified_files:
            date_str = cf.stem.replace("_classified", "")
            formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            out = report_dir / f"map_{date_str}.png"
            plot_classification_map(cf, out, f"{site_config['name']} — {formatted}")
            console.print(f"  ✓ Classification map: {out}")

    # RGB composites
    imagery_dir = Path("output") / site / "imagery"
    if imagery_dir.exists():
        for scene_dir in sorted(imagery_dir.iterdir()):
            if scene_dir.is_dir():
                date_str = scene_dir.name
                formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                out = report_dir / f"rgb_{date_str}.png"
                plot_rgb_composite(scene_dir, out, f"True Color — {formatted}")

    # Time series
    ts_path = Path("output") / site / "time_series.json"
    if ts_path.exists():
        with open(ts_path) as f:
            time_series = json.load(f)
        if time_series:
            plot_time_series(time_series, report_dir / "time_series.png", site_config["name"])

    console.print(f"\n[green]Report complete. Output: {report_dir}[/green]")


if __name__ == "__main__":
    main()
