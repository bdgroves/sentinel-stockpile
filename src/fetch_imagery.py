"""
fetch_imagery.py — Pull Sentinel-2 L2A imagery from Microsoft Planetary Computer.

Uses the STAC API to find cloud-free scenes over a site of interest,
then downloads the relevant bands for spectral analysis.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import click
import numpy as np
import planetary_computer
import rasterio
from pystac_client import Client
from pyproj import Transformer
from rasterio.transform import from_bounds
from rasterio.crs import CRS
from rich.console import Console
from rich.progress import track
from shapely.geometry import box, Point

console = Console()

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"

# Bands we need for our spectral indices
# B02=Blue, B03=Green, B04=Red, B08=NIR, B11=SWIR1, B12=SWIR2
BANDS = ["B02", "B03", "B04", "B08", "B11", "B12"]
BAND_RESOLUTION = {"B02": 10, "B03": 10, "B04": 10, "B08": 10, "B11": 20, "B12": 20}


def load_site(site_id: str) -> dict:
    """Load a site configuration from config/sites/."""
    config_path = Path("config/sites") / f"{site_id}.json"
    if not config_path.exists():
        console.print(f"[red]Site config not found: {config_path}[/red]")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


def site_bbox(site: dict) -> tuple[float, float, float, float]:
    """Create a bounding box around the site center point."""
    lat, lon = site["latitude"], site["longitude"]
    buf = site["buffer_meters"]

    # Project to UTM, buffer, project back
    point = Point(lon, lat)
    # Determine UTM zone
    utm_zone = int((lon + 180) / 6) + 1
    utm_crs = CRS.from_epsg(32600 + utm_zone)  # Northern hemisphere

    to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    to_wgs = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)

    ux, uy = to_utm.transform(lon, lat)
    minx, miny = to_wgs.transform(ux - buf, uy - buf)
    maxx, maxy = to_wgs.transform(ux + buf, uy + buf)

    return (minx, miny, maxx, maxy)


def search_scenes(
    bbox: tuple,
    start_date: str,
    end_date: str,
    max_cloud: int = 20,
) -> list:
    """Search Planetary Computer for Sentinel-2 scenes."""
    catalog = Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)

    search = catalog.search(
        collections=[COLLECTION],
        bbox=bbox,
        datetime=f"{start_date}/{end_date}",
        query={"eo:cloud_cover": {"lt": max_cloud}},
        sortby=[{"field": "properties.datetime", "direction": "asc"}],
        max_items=50,
    )

    items = list(search.items())
    console.print(f"[green]Found {len(items)} scenes with <{max_cloud}% cloud cover[/green]")
    return items


def download_bands(item, bbox: tuple, output_dir: Path, pixel_size: int = 10) -> dict:
    """Download and crop bands for a single scene."""
    date_str = item.datetime.strftime("%Y%m%d")
    scene_dir = output_dir / date_str
    scene_dir.mkdir(parents=True, exist_ok=True)

    band_paths = {}

    for band_name in BANDS:
        out_path = scene_dir / f"{band_name}.tif"
        if out_path.exists():
            band_paths[band_name] = out_path
            continue

        asset = item.assets[band_name]
        href = asset.href

        with rasterio.open(href) as src:
            # Transform bbox to source CRS
            to_src = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
            minx, miny = to_src.transform(bbox[0], bbox[1])
            maxx, maxy = to_src.transform(bbox[2], bbox[3])

            # Read window
            window = rasterio.windows.from_bounds(
                minx, miny, maxx, maxy, src.transform
            )
            data = src.read(1, window=window)

            # Write cropped output
            transform = from_bounds(
                minx, miny, maxx, maxy, data.shape[1], data.shape[0]
            )

            profile = src.profile.copy()
            profile.update(
                width=data.shape[1],
                height=data.shape[0],
                transform=transform,
                driver="GTiff",
                compress="deflate",
            )

            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(data, 1)

        band_paths[band_name] = out_path

    # Save scene metadata
    meta = {
        "date": date_str,
        "datetime": item.datetime.isoformat(),
        "cloud_cover": item.properties.get("eo:cloud_cover", None),
        "item_id": item.id,
        "bands": {k: str(v) for k, v in band_paths.items()},
    }
    with open(scene_dir / "metadata.json", "w") as f:
        json.dump(meta, f, indent=2)

    return band_paths


@click.command()
@click.option("--site", required=True, help="Site ID (matches config/sites/<id>.json)")
@click.option("--months", default=6, help="Number of months to look back")
@click.option("--max-cloud", default=20, help="Max cloud cover percentage")
def main(site: str, months: int, max_cloud: int):
    """Fetch Sentinel-2 imagery for a monitoring site."""
    site_config = load_site(site)
    console.print(f"\n[bold]🛰️  Fetching imagery for: {site_config['name']}[/bold]")
    console.print(f"    Commodity: {site_config['commodity']}")
    console.print(f"    Location: {site_config['latitude']:.4f}, {site_config['longitude']:.4f}")

    bbox = site_bbox(site_config)
    console.print(f"    Bbox: {bbox[0]:.4f}, {bbox[1]:.4f}, {bbox[2]:.4f}, {bbox[3]:.4f}")

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")
    console.print(f"    Date range: {start_date} → {end_date}")

    items = search_scenes(bbox, start_date, end_date, max_cloud)

    if not items:
        console.print("[yellow]No scenes found. Try increasing --max-cloud or --months.[/yellow]")
        return

    output_dir = Path("output") / site / "imagery"
    output_dir.mkdir(parents=True, exist_ok=True)

    for item in track(items, description="Downloading bands..."):
        try:
            download_bands(item, bbox, output_dir)
            console.print(f"  ✓ {item.datetime.strftime('%Y-%m-%d')} ({item.properties.get('eo:cloud_cover', '?')}% cloud)")
        except Exception as e:
            console.print(f"  [red]✗ {item.datetime.strftime('%Y-%m-%d')}: {e}[/red]")

    console.print(f"\n[green]Done. Imagery saved to {output_dir}[/green]")


if __name__ == "__main__":
    main()
