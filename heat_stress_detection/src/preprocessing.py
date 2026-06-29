"""
preprocessing.py — Data Preprocessing & Synthetic Demo Data Generator

Purpose:
    1. Generate realistic synthetic geospatial data for Delhi (used as demo data when
       real satellite imagery is not yet downloaded).
    2. Provide stubs for real Landsat preprocessing (cloud masking, reprojection, clipping).

Inputs:  n_points (int), random seed
Outputs: pandas DataFrame with columns:
         lat, lon, LST, NDVI, NDBI, NDWI, UHI_index, heat_zone,
         pop_density, dist_water, elevation, imperv_fraction,
         heat_stress_index, land_use, cluster_id, hotspot_score

Workflow:
    generate_delhi_demo_data()
        → spatial grid over Delhi bounding box
        → add heat from industrial/urban hotspot centres
        → subtract heat from green/water zones
        → compute NDVI, NDBI, NDWI, population density, elevation
        → compute UHI index & 5-class heat zone
        → compute composite heat stress index
        → assign land use labels
        → return DataFrame
"""

import logging
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Delhi spatial constants
# ---------------------------------------------------------------------------
DELHI_BOUNDS = {
    "lat_min": 28.40,
    "lat_max": 28.88,
    "lon_min": 76.84,
    "lon_max": 77.35,
}

# Real urban heat zones in Delhi (lat, lon, label, heat_intensity 0-1)
HOTSPOT_CENTRES = [
    (28.87, 77.09, "Narela Industrial Area", 0.95),
    (28.54, 77.27, "Okhla Industrial Estate", 0.90),
    (28.68, 77.28, "Shahdara Dense Urban", 0.85),
    (28.72, 77.11, "Rohini Residential Dense", 0.80),
    (28.62, 77.22, "Karol Bagh Commercial", 0.85),
    (28.58, 77.05, "Dwarka Sub-City", 0.75),
    (28.64, 77.30, "Mayur Vihar East", 0.78),
    (28.76, 77.15, "Outer Ring Road North", 0.72),
]

# Cool zones (forests, rivers, parks)
COOL_CENTRES = [
    (28.68, 77.19, "Delhi Ridge Forest", 0.90),
    (28.47, 77.08, "Tughlaqabad Forest", 0.85),
    (28.65, 77.25, "Yamuna River Corridor", 0.95),
    (28.60, 77.20, "Lodhi Garden", 0.80),
    (28.55, 77.17, "Sanjay Van", 0.88),
]

LAND_USE_CATEGORIES = [
    "Residential",
    "Industrial",
    "Commercial",
    "Green Space",
    "Water Body",
    "Transportation",
]
LAND_USE_PROBS = [0.38, 0.14, 0.20, 0.15, 0.06, 0.07]

# LST adjustment per land-use type (°C)
LAND_USE_LST_DELTA = {
    "Industrial": 4.5,
    "Commercial": 2.5,
    "Residential": 1.0,
    "Transportation": 2.0,
    "Green Space": -4.0,
    "Water Body": -5.5,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_delhi_demo_data(
    n_points: int = 8000,
    seed: int = 42,
    random_state: int = None,
    lat_min: float = None,
    lat_max: float = None,
    lon_min: float = None,
    lon_max: float = None,
    n_hotspot_centers: int = None,
    cool_zones: int = None,
) -> pd.DataFrame:
    """
    Generate realistic synthetic urban heat stress data.

    Supports any Indian city via optional bounding box override.

    Parameters
    ----------
    n_points : int
        Number of sample points (default 8000).
    seed / random_state : int
        Random seed for reproducibility (either param accepted).
    lat_min, lat_max, lon_min, lon_max : float
        Override spatial bounds for a different city.
    n_hotspot_centers : int
        Override number of hotspot centres (default: len(HOTSPOT_CENTRES)).
    cool_zones : int
        Override number of cool centres.

    Returns
    -------
    pd.DataFrame
        Feature-rich DataFrame ready for ML training and dashboard use.
    """
    # Accept random_state as alias for seed
    if random_state is not None:
        seed = random_state

    logger.info(f"Generating synthetic demo data — {n_points} points, seed={seed}")
    rng = np.random.default_rng(seed)

    # ── Spatial bounds ────────────────────────────────────────────────────
    _lat_min = lat_min if lat_min is not None else DELHI_BOUNDS["lat_min"]
    _lat_max = lat_max if lat_max is not None else DELHI_BOUNDS["lat_max"]
    _lon_min = lon_min if lon_min is not None else DELHI_BOUNDS["lon_min"]
    _lon_max = lon_max if lon_max is not None else DELHI_BOUNDS["lon_max"]

    lat_center = (_lat_min + _lat_max) / 2
    lon_center = (_lon_min + _lon_max) / 2
    lat_range  = _lat_max - _lat_min
    lon_range  = _lon_max - _lon_min

    # ── Hotspot centres (auto-generate if custom bounds given) ────────────
    n_hot = n_hotspot_centers if n_hotspot_centers is not None else len(HOTSPOT_CENTRES)
    n_cool = cool_zones if cool_zones is not None else len(COOL_CENTRES)

    if lat_min is not None:
        # Auto-generate hotspot/cool centres within the given bounds
        hot_centres = [
            (
                _lat_min + rng.uniform(0.1, 0.9) * lat_range,
                _lon_min + rng.uniform(0.1, 0.9) * lon_range,
                f"Hotspot Zone {i+1}",
                float(rng.uniform(0.70, 0.95)),
            )
            for i in range(n_hot)
        ]
        cool_centres = [
            (
                _lat_min + rng.uniform(0.1, 0.9) * lat_range,
                _lon_min + rng.uniform(0.1, 0.9) * lon_range,
                f"Green Zone {i+1}",
                float(rng.uniform(0.75, 0.92)),
            )
            for i in range(n_cool)
        ]
    else:
        hot_centres  = HOTSPOT_CENTRES
        cool_centres = COOL_CENTRES

    # ── Spatial sampling ──────────────────────────────────────────────────
    lat = rng.uniform(_lat_min, _lat_max, n_points)
    lon = rng.uniform(_lon_min, _lon_max, n_points)

    # ── Base LST (°C) ─────────────────────────────────────────────────────
    # Baseline ~35°C with spatial gradient (hotter in northern plains)
    lst = 35.0 + 3.0 * (_lat_max - lat) / (lat_range + 1e-8) + rng.normal(0, 1.2, n_points)

    # Add heat rings around hotspot centres
    for h_lat, h_lon, _name, intensity in hot_centres:
        dist = np.sqrt((lat - h_lat) ** 2 + (lon - h_lon) ** 2)
        lst += intensity * 9.0 * np.exp(-dist / 0.07)

    # Subtract heat around cool centres
    for c_lat, c_lon, _name, intensity in cool_centres:
        dist = np.sqrt((lat - c_lat) ** 2 + (lon - c_lon) ** 2)
        lst -= intensity * 6.0 * np.exp(-dist / 0.055)

    # Clip to realistic range for Indian summer city
    lst = np.clip(lst, 27.0, 53.0)

    # ── Spectral indices ──────────────────────────────────────────────────
    # NDVI: inversely correlated with LST (vegetation cools surface)
    ndvi = 0.62 - 0.013 * (lst - 27) + rng.normal(0, 0.07, n_points)
    ndvi = np.clip(ndvi, -0.15, 0.80)

    # NDBI: Built-up index, positively correlated with LST
    ndbi = -0.35 + 0.016 * (lst - 27) + rng.normal(0, 0.055, n_points)
    ndbi = np.clip(ndbi, -0.55, 0.65)

    # NDWI: Water index — high near a city's primary water body (e.g. Yamuna)
    ndwi_base = -0.18 + rng.normal(0, 0.09, n_points)
    # Place a water body at 70% of the longitude span (eastern river)
    water_lat = _lat_min + 0.55 * lat_range
    water_lon = _lon_min + 0.70 * lon_range
    water_dist = np.sqrt((lat - water_lat) ** 2 + (lon - water_lon) ** 2)
    ndwi_base += 0.50 * np.exp(-water_dist / max(0.04, lat_range * 0.08))
    ndwi = np.clip(ndwi_base, -0.65, 0.85)

    # ── Ancillary features ────────────────────────────────────────────────
    # Population density (persons / km²): log-normal, higher in dense urban cores
    base_pop = rng.lognormal(8.5, 1.1, n_points)
    for h_lat, h_lon, _name, intensity in hot_centres[:4]:
        dist = np.sqrt((lat - h_lat) ** 2 + (lon - h_lon) ** 2)
        base_pop += intensity * 30000 * np.exp(-dist / 0.06)
    pop_density = np.clip(base_pop, 300, 90000)

    # Distance to nearest water body (km)
    dist_water = water_dist * 111.0  # degrees → km approx
    dist_water = np.clip(dist_water, 0.1, 35.0)

    # Elevation (m): generic city elevation with slight gradient
    base_elev = 200 if lat_min is None else float(rng.uniform(5, 900))
    elevation = base_elev + 25 * (lat_center - lat) - 15 * (lon - lon_center) + rng.normal(0, 4, n_points)
    elevation = np.clip(elevation, max(0, base_elev - 50), base_elev + 100)

    # Imperviousness fraction (0-1): fraction of pixel covered by impervious surface
    imperv = 0.15 + 0.018 * (lst - 27) + rng.normal(0, 0.045, n_points)
    imperv = np.clip(imperv, 0.0, 1.0)

    # ── UHI index & heat zone classification ──────────────────────────────
    lst_mean = float(np.mean(lst))
    lst_std = float(np.std(lst))
    uhi = (lst - lst_mean) / lst_std

    heat_zone = _classify_uhi_vectorised(uhi)

    # ── Heat stress index (composite 0-1) ─────────────────────────────────
    def _norm(x: np.ndarray) -> np.ndarray:
        rng_val = x.max() - x.min()
        return (x - x.min()) / rng_val if rng_val > 0 else np.zeros_like(x)

    heat_stress = (
        0.40 * _norm(lst)
        + 0.20 * _norm(ndbi)
        + 0.20 * _norm(pop_density)
        + 0.10 * _norm(imperv)
        + 0.10 * (1.0 - _norm(ndvi))
    )
    heat_stress = np.clip(heat_stress, 0.0, 1.0)

    # ── Land use assignment ───────────────────────────────────────────────
    land_use = rng.choice(LAND_USE_CATEGORIES, n_points, p=LAND_USE_PROBS)

    # Fine-tune LST by land use
    for lu, delta in LAND_USE_LST_DELTA.items():
        mask = land_use == lu
        lst[mask] = np.clip(lst[mask] + delta, 27.0, 53.0)

    # Recompute UHI and heat stress after land-use adjustment
    lst_mean2 = float(np.mean(lst))
    lst_std2 = float(np.std(lst))
    uhi = (lst - lst_mean2) / lst_std2
    heat_zone = _classify_uhi_vectorised(uhi)
    heat_stress = np.clip(
        0.40 * _norm(lst) + 0.20 * _norm(ndbi) + 0.20 * _norm(pop_density)
        + 0.10 * _norm(imperv) + 0.10 * (1.0 - _norm(ndvi)),
        0.0, 1.0,
    )

    # ── Assemble DataFrame ────────────────────────────────────────────────
    df = pd.DataFrame(
        {
            "lat": lat,
            "lon": lon,
            "LST": np.round(lst, 2),
            "NDVI": np.round(ndvi, 4),
            "NDBI": np.round(ndbi, 4),
            "NDWI": np.round(ndwi, 4),
            "UHI_index": np.round(uhi, 4),
            "heat_zone": heat_zone,
            "pop_density": np.round(pop_density, 0).astype(int),
            "dist_water": np.round(dist_water, 3),
            "elevation": np.round(elevation, 1),
            "imperv_fraction": np.round(imperv, 4),
            "heat_stress_index": np.round(heat_stress, 4),
            "land_use": land_use,
        }
    )

    logger.info(
        f"Data generated: LST range {df['LST'].min():.1f}–{df['LST'].max():.1f}°C | "
        f"Heat zones: {df['heat_zone'].value_counts().to_dict()}"
    )
    return df


HEAT_ZONE_THRESHOLDS = {
    "Very Low":  (-np.inf, -1.5),
    "Low":       (-1.5, -0.5),
    "Moderate":  (-0.5, 0.5),
    "High":      (0.5, 1.5),
    "Extreme":   (1.5, np.inf),
}


def compute_uhi_index(df: pd.DataFrame, lst_col: str = "LST") -> pd.DataFrame:
    """
    Compute Urban Heat Island (UHI) index as z-score of LST.

    UHI = (LST_i - mean(LST)) / std(LST)

    Parameters
    ----------
    df      : DataFrame with LST column
    lst_col : Column name for land surface temperature

    Returns
    -------
    DataFrame with added 'uhi_index' column
    """
    df = df.copy()
    lst_vals = df[lst_col].values.astype(float)
    std = lst_vals.std()
    if std == 0:
        df["uhi_index"] = 0.0
    else:
        df["uhi_index"] = np.round((lst_vals - lst_vals.mean()) / std, 4)
    return df


def assign_heat_zones(df: pd.DataFrame, uhi_col: str = "uhi_index") -> pd.DataFrame:
    """
    Assign 5-class heat zone labels based on UHI index.

    Parameters
    ----------
    df      : DataFrame with uhi_index column
    uhi_col : Column name for UHI index

    Returns
    -------
    DataFrame with added 'heat_zone' column
    """
    df = df.copy()
    df["heat_zone"] = _classify_uhi_vectorised(df[uhi_col].values)
    return df


def _classify_uhi_vectorised(uhi: np.ndarray) -> np.ndarray:
    """Map UHI index values to 5-class heat zone labels."""
    conditions = [
        uhi < -1.5,
        (uhi >= -1.5) & (uhi < -0.5),
        (uhi >= -0.5) & (uhi < 0.5),
        (uhi >= 0.5) & (uhi < 1.5),
        uhi >= 1.5,
    ]
    choices = ["Very Low", "Low", "Moderate", "High", "Extreme"]
    return np.select(conditions, choices, default="Moderate")


# ---------------------------------------------------------------------------
# Real Landsat preprocessing stubs (used when actual satellite data exists)
# ---------------------------------------------------------------------------

def apply_cloud_mask(data: np.ndarray, qa_band: np.ndarray, threshold: int = 21824) -> np.ndarray:
    """
    Apply cloud masking using Landsat QA_PIXEL band.

    Parameters
    ----------
    data : np.ndarray  — raster band array
    qa_band : np.ndarray  — QA_PIXEL band array
    threshold : int  — QA bitmask value for clear pixels (default 21824 = clear land)

    Returns
    -------
    np.ndarray with cloud pixels set to NaN
    """
    cloud_mask = (qa_band & threshold) == 0
    masked = data.astype(float)
    masked[cloud_mask] = np.nan
    return masked


def dn_to_toa_reflectance(dn: np.ndarray, mult: float, add: float) -> np.ndarray:
    """Convert raw DN values to Top-of-Atmosphere reflectance."""
    return mult * dn + add


def reproject_match(src_data: np.ndarray, src_transform, src_crs,
                    dst_crs: str = "EPSG:32643") -> np.ndarray:
    """
    Stub: reproject raster to target CRS (UTM Zone 43N for Delhi).
    Requires rasterio.warp in production use.
    """
    logger.warning("reproject_match: stub — install rasterio and use warp.reproject()")
    return src_data


def clip_to_boundary(data: np.ndarray, boundary_geom) -> np.ndarray:
    """
    Stub: clip raster to city boundary polygon.
    Requires rasterio.mask in production use.
    """
    logger.warning("clip_to_boundary: stub — install rasterio and use rasterio.mask.mask()")
    return data
