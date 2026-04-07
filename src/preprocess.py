"""
preprocess.py — Cloud masking and band alignment.

Resamples 20m bands (B11, B12) to 10m to match the optical bands,
and provides utilities for reading aligned band stacks.
"""

import numpy as np
import rasterio
from rasterio.enums import Resampling
from pathlib import Path


def load_band(path: Path) -> tuple[np.ndarray, dict]:
    """Load a single band, return (data, profile)."""
    with rasterio.open(path) as src:
        data = src.read(1).astype(np.float32)
        profile = src.profile.copy()
    return data, profile


def resample_to_10m(data_20m: np.ndarray, target_shape: tuple) -> np.ndarray:
    """Resample 20m data to match 10m grid using bilinear interpolation."""
    from scipy.ndimage import zoom

    zoom_y = target_shape[0] / data_20m.shape[0]
    zoom_x = target_shape[1] / data_20m.shape[1]
    return zoom(data_20m, (zoom_y, zoom_x), order=1)


def load_scene_stack(scene_dir: Path) -> tuple[dict, dict]:
    """
    Load all bands for a scene, aligned to 10m resolution.

    Returns:
        bands: dict of band_name -> np.ndarray (float32, reflectance 0-10000)
        profile: rasterio profile for the 10m grid
    """
    bands_10m = {}
    profile_10m = None

    # Load 10m bands first to get reference shape
    for band_name in ["B02", "B03", "B04", "B08"]:
        band_path = scene_dir / f"{band_name}.tif"
        if band_path.exists():
            data, profile = load_band(band_path)
            bands_10m[band_name] = data
            if profile_10m is None:
                profile_10m = profile
                ref_shape = data.shape

    # Load and resample 20m bands
    for band_name in ["B11", "B12"]:
        band_path = scene_dir / f"{band_name}.tif"
        if band_path.exists():
            data, _ = load_band(band_path)
            bands_10m[band_name] = resample_to_10m(data, ref_shape)

    return bands_10m, profile_10m


def to_reflectance(data: np.ndarray) -> np.ndarray:
    """Convert DN values to reflectance (0-1 range)."""
    return np.clip(data / 10000.0, 0, 1)
