"""
measure.py — Compute stockpile area measurements over time.

Reads classified rasters, calculates area in square meters for each class,
and builds a time series CSV.
"""

import json
import sys
from pathlib import Path

import click
import numpy as np
import rasterio
from rich.console import Console
from rich.table import Table

console = Console()

CLASS_NAMES = {1: "water", 2: "vegetation", 3: "stockpile", 4: "ground"}


def pixel_area_m2(profile: dict) -> float:
    """Calculate the area of a single pixel in square meters."""
    transform = profile["transform"]
    # Pixel dimensions in CRS units (should be meters for UTM)
    pixel_width = abs(transform.a)
    pixel_height = abs(transform.e)
    return pixel_width * pixel_height


def measure_scene(classified_path: Path) -> dict:
    """Measure area of each class in a classified raster."""
    with rasterio.open(classified_path) as src:
        data = src.read(1)
        area_per_pixel = pixel_area_m2(src.profile)

    results = {}
    unique, counts = np.unique(data, return_counts=True)

    for cls_val, cls_count in zip(unique, counts):
        cls_name = CLASS_NAMES.get(cls_val, f"unknown_{cls_val}")
        area_m2 = float(cls_count * area_per_pixel)
        results[cls_name] = {
            "pixel_count": int(cls_count),
            "area_m2": area_m2,
            "area_hectares": area_m2 / 10000.0,
        }

    total_pixels = int(np.sum(counts))
    stockpile = results.get("stockpile", {"pixel_count": 0, "area_m2": 0})
    results["stockpile_fraction"] = stockpile["pixel_count"] / total_pixels if total_pixels > 0 else 0

    return results


@click.command()
@click.option("--site", required=True, help="Site ID")
def main(site: str):
    """Measure stockpile areas across all classified scenes."""
    site_path = Path("config/sites") / f"{site}.json"
    with open(site_path) as f:
        site_config = json.load(f)

    classify_dir = Path("output") / site / "classified"
    if not classify_dir.exists():
        console.print("[red]No classified scenes found. Run detect first.[/red]")
        sys.exit(1)

    classified_files = sorted(classify_dir.glob("*_classified.tif"))
    console.print(f"\n[bold]📏 Measuring {len(classified_files)} scenes for {site_config['name']}[/bold]")

    time_series = []

    for cf in classified_files:
        date_str = cf.stem.replace("_classified", "")
        measurements = measure_scene(cf)
        stockpile = measurements.get("stockpile", {})

        entry = {
            "date": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}",
            "stockpile_m2": stockpile.get("area_m2", 0),
            "stockpile_ha": stockpile.get("area_hectares", 0),
            "stockpile_fraction": measurements.get("stockpile_fraction", 0),
            "all_classes": measurements,
        }
        time_series.append(entry)

    # Save time series
    output_dir = Path("output") / site
    ts_path = output_dir / "time_series.json"
    with open(ts_path, "w") as f:
        json.dump(time_series, f, indent=2)

    # Save CSV for easy analysis
    csv_path = output_dir / "time_series.csv"
    with open(csv_path, "w") as f:
        f.write("date,stockpile_m2,stockpile_ha,stockpile_fraction\n")
        for entry in time_series:
            f.write(f"{entry['date']},{entry['stockpile_m2']:.1f},{entry['stockpile_ha']:.4f},{entry['stockpile_fraction']:.4f}\n")

    # Print summary table
    table = Table(title=f"Stockpile Measurements — {site_config['name']}")
    table.add_column("Date", style="cyan")
    table.add_column("Area (m²)", justify="right", style="green")
    table.add_column("Area (ha)", justify="right")
    table.add_column("% of Site", justify="right")
    table.add_column("Δ from prev", justify="right", style="bold")

    prev_area = None
    for entry in time_series:
        area = entry["stockpile_m2"]
        delta = ""
        if prev_area is not None:
            diff = area - prev_area
            pct = (diff / prev_area * 100) if prev_area > 0 else 0
            color = "green" if diff > 0 else "red" if diff < 0 else "white"
            delta = f"[{color}]{diff:+,.0f} m² ({pct:+.1f}%)[/{color}]"
        prev_area = area

        table.add_row(
            entry["date"],
            f"{area:,.0f}",
            f"{entry['stockpile_ha']:.2f}",
            f"{entry['stockpile_fraction']:.1%}",
            delta,
        )

    console.print(table)
    console.print(f"\n[green]Time series saved to {ts_path} and {csv_path}[/green]")


if __name__ == "__main__":
    main()
