"""
classify.py — Spectral classification of stockpile pixels.

Computes spectral indices (NDVI, NDMI, BSI, Brightness) and classifies
each pixel as stockpile, ground, vegetation, or water.
"""

import json
import sys
from pathlib import Path

import click
import numpy as np
import rasterio
from rich.console import Console

from preprocess import load_scene_stack, to_reflectance

console = Console()


def safe_index(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute (a - b) / (a + b), handling division by zero."""
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where((a + b) != 0, (a - b) / (a + b), 0.0)
    return result.astype(np.float32)


def compute_indices(bands: dict) -> dict:
    """
    Compute spectral indices from band stack.

    Returns dict of index_name -> np.ndarray
    """
    red = to_reflectance(bands["B04"])
    green = to_reflectance(bands["B03"])
    blue = to_reflectance(bands["B02"])
    nir = to_reflectance(bands["B08"])
    swir1 = to_reflectance(bands["B11"])
    swir2 = to_reflectance(bands["B12"])

    indices = {}

    # NDVI — vegetation vs non-vegetation
    # High (>0.3) = vegetation, Low (<0.1) = bare/built
    indices["ndvi"] = safe_index(nir, red)

    # NDMI — moisture content
    # Fresh-cut lumber has higher moisture than dried stock or pavement
    indices["ndmi"] = safe_index(nir, swir1)

    # BSI — Bare Soil Index
    # Separates bare ground from stacked material
    indices["bsi"] = safe_index((swir1 + red), (nir + blue))

    # NDWI — water detection
    indices["ndwi"] = safe_index(green, nir)

    # Brightness — mean visible reflectance
    # Containers and tarped lumber are bright; shadows and water are dark
    indices["brightness"] = (red + green + blue) / 3.0

    # SWIR ratio — material texture indicator
    indices["swir_ratio"] = safe_index(swir1, swir2)

    return indices


# Classification thresholds (tunable per commodity type)
THRESHOLDS = {
    "lumber": {
        "water_ndwi": 0.1,
        "veg_ndvi": 0.35,
        "stockpile_bsi_min": 0.03,
        "stockpile_brightness_min": 0.175,
        "stockpile_brightness_max": 0.25,
    },
    "containers": {
        "water_ndwi": 0.1,
        "veg_ndvi": 0.35,
        "stockpile_bsi_min": -0.2,
        "stockpile_brightness_min": 0.10,
        "stockpile_brightness_max": 0.50,
    },
    "wind_components": {
        "water_ndwi": 0.1,
        "veg_ndvi": 0.35,
        "stockpile_bsi_min": -0.05,
        "stockpile_brightness_min": 0.22,
        "stockpile_brightness_max": 0.50,
    },
}

# Classification codes
CLASS_WATER = 1
CLASS_VEGETATION = 2
CLASS_STOCKPILE = 3
CLASS_GROUND = 4
CLASS_NAMES = {1: "water", 2: "vegetation", 3: "stockpile", 4: "ground"}


def classify_pixels(indices: dict, commodity: str = "lumber") -> np.ndarray:
    """
    Classify each pixel into land cover type.

    Returns integer array: 1=water, 2=vegetation, 3=stockpile, 4=ground
    """
    t = THRESHOLDS.get(commodity, THRESHOLDS["lumber"])
    shape = indices["ndvi"].shape
    classified = np.full(shape, CLASS_GROUND, dtype=np.uint8)

    # Water (highest priority)
    water_mask = indices["ndwi"] > t["water_ndwi"]
    classified[water_mask] = CLASS_WATER

    # Vegetation
    veg_mask = (~water_mask) & (indices["ndvi"] > t["veg_ndvi"])
    classified[veg_mask] = CLASS_VEGETATION

    # Stockpile — not water, not vegetation, within brightness and BSI range
    stockpile_mask = (
        (~water_mask)
        & (~veg_mask)
        & (indices["bsi"] > t["stockpile_bsi_min"])
        & (indices["brightness"] > t["stockpile_brightness_min"])
        & (indices["brightness"] < t["stockpile_brightness_max"])
    )
    classified[stockpile_mask] = CLASS_STOCKPILE

    # Everything else stays as ground
    return classified


@click.command()
@click.option("--site", required=True, help="Site ID")
def main(site: str):
    """Run spectral classification on all fetched scenes for a site."""
    site_path = Path("config/sites") / f"{site}.json"
    with open(site_path) as f:
        site_config = json.load(f)

    commodity = site_config.get("commodity", "lumber")
    imagery_dir = Path("output") / site / "imagery"

    if not imagery_dir.exists():
        console.print("[red]No imagery found. Run fetch first.[/red]")
        sys.exit(1)

    scene_dirs = sorted([d for d in imagery_dir.iterdir() if d.is_dir()])
    console.print(f"\n[bold]🔬 Classifying {len(scene_dirs)} scenes for {site_config['name']}[/bold]")
    console.print(f"    Commodity type: {commodity}")

    classify_dir = Path("output") / site / "classified"
    classify_dir.mkdir(parents=True, exist_ok=True)

    for scene_dir in scene_dirs:
        date_str = scene_dir.name
        out_path = classify_dir / f"{date_str}_classified.tif"

        if out_path.exists():
            console.print(f"  ⏭  {date_str} (already classified)")
            continue

        try:
            bands, profile = load_scene_stack(scene_dir)
            if not bands or profile is None:
                console.print(f"  [yellow]⚠  {date_str}: missing bands[/yellow]")
                continue

            indices = compute_indices(bands)
            classified = classify_pixels(indices, commodity)

            # Write classification raster
            profile.update(dtype="uint8", count=1, nodata=0, compress="deflate")
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(classified, 1)

            # Count pixels per class
            unique, counts = np.unique(classified, return_counts=True)
            class_counts = {CLASS_NAMES.get(u, "?"): int(c) for u, c in zip(unique, counts)}
            console.print(f"  ✓ {date_str}: {class_counts}")

            # Save index rasters for debugging/visualization
            index_dir = classify_dir / f"{date_str}_indices"
            index_dir.mkdir(exist_ok=True)
            idx_profile = profile.copy()
            idx_profile.update(dtype="float32", nodata=np.nan)
            for idx_name, idx_data in indices.items():
                with rasterio.open(index_dir / f"{idx_name}.tif", "w", **idx_profile) as dst:
                    dst.write(idx_data, 1)

        except Exception as e:
            console.print(f"  [red]✗ {date_str}: {e}[/red]")

    console.print(f"\n[green]Classification complete. Output: {classify_dir}[/green]")


if __name__ == "__main__":
    main()
