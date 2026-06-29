"""
hotspot_detector.py — Spatial Hotspot Detection Engine

Purpose:
    1. Getis-Ord Gi* statistic — statistically significant spatial clusters of high LST.
    2. DBSCAN clustering — group hotspot pixels into named zones.
    3. Composite severity scoring — rank hotspots by risk to human population.
    4. Export top-N hotspot zones as GeoJSON.

Algorithm:
    Getis-Ord Gi*:
        Z-score > 1.96 (p < 0.05) → Hotspot
        Z-score < -1.96            → Coldspot
    DBSCAN:
        eps ≈ 0.005° (~500m), min_samples = 30 pixels
        Clusters contiguous hotspot pixels into zones

Inputs:  GeoDataFrame or DataFrame with lat, lon, LST, pop_density, NDVI
Outputs: DataFrame with cluster_id, hotspot_score, severity; GeoJSON file
"""

import json
import logging
from typing import Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Severity weight factors (must sum to 1.0)
SEVERITY_WEIGHTS = {
    "LST": 0.40,
    "pop_density": 0.25,
    "NDVI": 0.15,       # inverted — low NDVI worsens heat
    "NDBI": 0.10,
    "imperv_fraction": 0.10,
}


# ---------------------------------------------------------------------------
# Getis-Ord Gi* (simplified spatial z-score implementation)
# ---------------------------------------------------------------------------

def detect_hotspots_gistar(
    df: pd.DataFrame,
    value_col: str = "LST",
    radius_deg: float = 0.03,
    z_threshold: float = 1.96,
) -> pd.DataFrame:
    """
    Detect statistically significant hotspots using a simplified Getis-Ord Gi* approach.

    For each point, the local Gi* statistic compares the mean of neighbours
    within `radius_deg` to the global mean, normalised by the global std.

    Parameters
    ----------
    df          : DataFrame with 'lat', 'lon', and value_col columns
    value_col   : Column to analyse (default 'LST')
    radius_deg  : Neighbourhood radius in decimal degrees (~3km at Delhi latitude)
    z_threshold : Z-score threshold for significance (1.96 → p<0.05)

    Returns
    -------
    DataFrame with added columns: gi_z_score, is_hotspot, is_coldspot
    """
    logger.info(f"Running Gi* statistic on '{value_col}' with radius={radius_deg}°")
    df = df.copy()
    lat = df["lat"].values
    lon = df["lon"].values
    values = df[value_col].values
    global_mean = np.mean(values)
    global_std = np.std(values)
    n = len(df)

    # Vectorised distance computation — chunked to avoid OOM on large datasets
    gi_z = np.zeros(n)
    chunk = 500  # process 500 points at a time

    for start in range(0, n, chunk):
        end = min(start + chunk, n)
        # Distance matrix for this chunk vs all points
        dlat = lat[start:end, None] - lat[None, :]
        dlon = lon[start:end, None] - lon[None, :]
        dist = np.sqrt(dlat ** 2 + dlon ** 2)
        # Weights: 1 if within radius, else 0
        W = (dist <= radius_deg).astype(float)
        n_i = W.sum(axis=1)
        local_mean = (W * values[None, :]).sum(axis=1) / np.where(n_i > 0, n_i, 1)
        gi_z[start:end] = (local_mean - global_mean) / (global_std / np.sqrt(np.where(n_i > 0, n_i, 1)))

    df["gi_z_score"] = np.round(gi_z, 3)
    df["is_hotspot"] = gi_z > z_threshold
    df["is_coldspot"] = gi_z < -z_threshold

    n_hot = df["is_hotspot"].sum()
    n_cold = df["is_coldspot"].sum()
    logger.info(f"Gi* complete: {n_hot} hotspot pixels | {n_cold} coldspot pixels")
    return df


# ---------------------------------------------------------------------------
# DBSCAN Spatial Clustering
# ---------------------------------------------------------------------------

def cluster_hotspots_dbscan(
    df: pd.DataFrame,
    eps_deg: float = 0.03,
    min_samples: int = 10,
) -> pd.DataFrame:
    """
    Group hotspot pixels into contiguous zones using pure-numpy grid clustering.

    Replaces sklearn DBSCAN to eliminate the scipy.stats DLL dependency on
    Windows systems where the C: drive pagefile may be full.

    Algorithm:
        1. Bin hotspot pixels into grid cells of size eps_deg × eps_deg.
        2. For each pixel, count neighbours within eps_deg (Linf norm).
        3. Pixels with ≥ min_samples neighbours become 'core' and are
           assigned the cluster ID of their grid cell.
        4. Noise pixels (< min_samples neighbours) get cluster_id = -1.

    Parameters
    ----------
    df          : DataFrame with 'lat', 'lon', 'is_hotspot' columns
    eps_deg     : Neighbourhood radius in degrees (default 0.03 ≈ 3 km)
    min_samples : Minimum neighbours to be a core point (default 10)

    Returns
    -------
    DataFrame with added 'cluster_id' column (-1 = noise / not hotspot)
    """
    df = df.copy()
    df["cluster_id"] = -1

    hotspot_mask = df["is_hotspot"].values
    n_hot = int(hotspot_mask.sum())
    if n_hot == 0:
        logger.warning("No hotspot pixels found — cannot run clustering")
        return df

    h_lat = df.loc[hotspot_mask, "lat"].values
    h_lon = df.loc[hotspot_mask, "lon"].values

    # Assign each hotspot pixel to a grid cell
    grid_lat = np.round(h_lat / eps_deg).astype(int)
    grid_lon = np.round(h_lon / eps_deg).astype(int)
    cell_key = grid_lat.astype(np.int64) * 1_000_000 + grid_lon.astype(np.int64)
    _, cell_ids = np.unique(cell_key, return_inverse=True)

    # Count neighbours within eps_deg (Linf / Chebyshev metric) — chunked
    local_counts = np.zeros(n_hot, dtype=np.int32)
    chunk = 300
    for start in range(0, n_hot, chunk):
        end = min(start + chunk, n_hot)
        dlat = np.abs(h_lat[start:end, None] - h_lat[None, :])
        dlon = np.abs(h_lon[start:end, None] - h_lon[None, :])
        local_counts[start:end] = ((dlat <= eps_deg) & (dlon <= eps_deg)).sum(axis=1)

    # Core points: >= min_samples neighbours
    is_core = local_counts >= min_samples
    raw_labels = np.where(is_core, cell_ids, -1)

    # Re-number clusters 0, 1, 2, ...
    valid_ids = np.unique(raw_labels[raw_labels >= 0])
    id_map = {old: new for new, old in enumerate(valid_ids)}
    final_labels = np.vectorize(lambda x: id_map.get(x, -1))(raw_labels)

    df.loc[hotspot_mask, "cluster_id"] = final_labels
    n_clusters = len(valid_ids)
    logger.info(f"DBSCAN found {n_clusters} hotspot clusters")
    return df


# ---------------------------------------------------------------------------
# Composite Severity Score
# ---------------------------------------------------------------------------

def calculate_severity_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute a composite severity score (0–1) for each data point.

    Score = Σ(weight × normalised_feature)
    Higher score → more severe heat stress risk.

    Parameters
    ----------
    df : DataFrame with LST, pop_density, NDVI, NDBI, imperv_fraction columns

    Returns
    -------
    DataFrame with added 'hotspot_score' column
    """
    df = df.copy()

    def _norm(series: pd.Series) -> pd.Series:
        mn, mx = series.min(), series.max()
        if mx == mn:
            return pd.Series(np.zeros(len(series)), index=series.index)
        return (series - mn) / (mx - mn)

    score = (
        SEVERITY_WEIGHTS["LST"] * _norm(df["LST"])
        + SEVERITY_WEIGHTS["pop_density"] * _norm(df["pop_density"])
        + SEVERITY_WEIGHTS["NDVI"] * (1 - _norm(df["NDVI"]))   # low NDVI = worse
        + SEVERITY_WEIGHTS["NDBI"] * _norm(df["NDBI"])
        + SEVERITY_WEIGHTS["imperv_fraction"] * _norm(df["imperv_fraction"])
    )

    df["hotspot_score"] = np.round(score.values, 4)
    return df


# ---------------------------------------------------------------------------
# Cluster-level aggregation and ranking
# ---------------------------------------------------------------------------

def identify_top_hotspots(df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """
    Aggregate DBSCAN clusters into zone-level statistics and rank by severity.

    Parameters
    ----------
    df    : DataFrame with cluster_id, hotspot_score, LST, pop_density, lat, lon
    top_n : Number of top hotspot zones to return

    Returns
    -------
    DataFrame with one row per cluster, sorted by descending severity score.
    Columns: cluster_id, centroid_lat, centroid_lon, mean_LST, max_LST,
             total_population, mean_hotspot_score, n_pixels, severity_label, zone_name
    """
    valid = df[df["cluster_id"] >= 0].copy()

    if valid.empty:
        logger.warning("No valid clusters found — returning empty DataFrame")
        return pd.DataFrame()

    agg = (
        valid.groupby("cluster_id")
        .agg(
            centroid_lat=("lat", "mean"),
            centroid_lon=("lon", "mean"),
            mean_LST=("LST", "mean"),
            max_LST=("LST", "max"),
            mean_NDVI=("NDVI", "mean"),
            mean_NDBI=("NDBI", "mean"),
            mean_hotspot_score=("hotspot_score", "mean"),
            n_pixels=("LST", "count"),
            total_population=("pop_density", "sum"),
        )
        .reset_index()
    )

    # Estimated area (each point ≈ 30m Landsat pixel → 900 m²)
    agg["area_km2"] = (agg["n_pixels"] * 900 / 1_000_000).round(2)

    # Severity label
    agg["severity_label"] = pd.cut(
        agg["mean_hotspot_score"],
        bins=[0, 0.3, 0.5, 0.7, 0.85, 1.0],
        labels=["Low", "Moderate", "High", "Very High", "Critical"],
    )

    # Generate human-readable zone names
    agg["zone_name"] = agg.apply(
        lambda r: _name_zone(r["centroid_lat"], r["centroid_lon"], int(r["cluster_id"])),
        axis=1,
    )

    agg = agg.sort_values("mean_hotspot_score", ascending=False).head(top_n).reset_index(drop=True)
    agg["rank"] = agg.index + 1

    # Round numeric columns
    for col in ["centroid_lat", "centroid_lon", "mean_LST", "max_LST",
                "mean_NDVI", "mean_NDBI", "mean_hotspot_score"]:
        agg[col] = agg[col].round(4)
    agg["total_population"] = agg["total_population"].astype(int)

    logger.info(f"Top-{len(agg)} hotspot zones identified")
    return agg


def _name_zone(lat: float, lon: float, cluster_id: int) -> str:
    """Map cluster centroid to a Delhi locality name."""
    LOCALITY_MAP = [
        (28.87, 77.09, "Narela Industrial Area"),
        (28.54, 77.27, "Okhla Industrial Estate"),
        (28.68, 77.28, "Shahdara"),
        (28.72, 77.11, "Rohini"),
        (28.62, 77.22, "Karol Bagh"),
        (28.58, 77.05, "Dwarka"),
        (28.64, 77.30, "Mayur Vihar"),
        (28.76, 77.15, "Outer Ring Road – North"),
        (28.50, 77.15, "Saket – South Delhi"),
        (28.66, 77.22, "Civil Lines"),
        (28.55, 77.22, "Lajpat Nagar"),
        (28.71, 77.20, "Pitampura"),
    ]
    best_name = f"Hotspot Zone {cluster_id + 1}"
    best_dist = 999.0
    for h_lat, h_lon, name in LOCALITY_MAP:
        d = ((lat - h_lat) ** 2 + (lon - h_lon) ** 2) ** 0.5
        if d < best_dist:
            best_dist = d
            best_name = name
    return best_name if best_dist < 0.15 else f"Hotspot Zone {cluster_id + 1}"


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def create_hotspot_geojson(hotspot_df: pd.DataFrame) -> dict:
    """
    Convert hotspot zone DataFrame to GeoJSON FeatureCollection.

    Each cluster centroid becomes a Point feature with all zone properties.

    Returns
    -------
    dict — GeoJSON FeatureCollection
    """
    features = []
    for _, row in hotspot_df.iterrows():
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(row["centroid_lon"]), float(row["centroid_lat"])],
            },
            "properties": {
                "rank": int(row["rank"]),
                "zone_name": str(row["zone_name"]),
                "mean_LST": float(row["mean_LST"]),
                "max_LST": float(row["max_LST"]),
                "severity_label": str(row["severity_label"]),
                "hotspot_score": float(row["mean_hotspot_score"]),
                "area_km2": float(row["area_km2"]),
                "total_population": int(row["total_population"]),
                "n_pixels": int(row["n_pixels"]),
            },
        }
        features.append(feature)

    return {"type": "FeatureCollection", "features": features}


def run_full_hotspot_pipeline(df: pd.DataFrame, top_n: int = 20) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    End-to-end hotspot detection pipeline.

    Steps:
        1. Gi* significance test
        2. Severity scoring
        3. DBSCAN clustering
        4. Cluster aggregation & ranking
        5. GeoJSON export

    Returns
    -------
    (annotated_df, hotspot_zones_df, geojson_dict)
    """
    logger.info("=== Starting full hotspot detection pipeline ===")
    df = detect_hotspots_gistar(df)
    df = calculate_severity_scores(df)
    df = cluster_hotspots_dbscan(df)
    hotspot_zones = identify_top_hotspots(df, top_n=top_n)
    geojson = create_hotspot_geojson(hotspot_zones)
    logger.info("=== Hotspot pipeline complete ===")
    return df, hotspot_zones, geojson
