"""
data_loader.py — Centralised Data Loading & Caching

Purpose:
    Single entry point for all data loading operations in the dashboard.
    Handles: demo CSV, hotspot GeoJSON, trained model bundles, city statistics.

Design:
    All heavy I/O is wrapped in @st.cache_data or @st.cache_resource decorators
    when called from Streamlit. This module provides plain functions; the
    Streamlit app wraps them with caching decorators.
"""

import json
import logging
import os
from typing import Dict, Optional, Tuple

import joblib
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DEMO_DIR = os.path.join(PROJECT_ROOT, "data", "demo")
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
OUTPUTS_DIR = os.path.join(PROJECT_ROOT, "outputs")

DEMO_CSV_PATH = os.path.join(DATA_DEMO_DIR, "delhi_heat_stress.csv")
HOTSPOT_GEOJSON_PATH = os.path.join(DATA_DEMO_DIR, "hotspot_zones.geojson")
HOTSPOT_CSV_PATH = os.path.join(DATA_DEMO_DIR, "hotspot_zones.csv")
RF_MODEL_PATH = os.path.join(MODELS_DIR, "heat_stress_rf.pkl")
GB_MODEL_PATH = os.path.join(MODELS_DIR, "heat_stress_gb.pkl")


# ---------------------------------------------------------------------------
# Core loaders
# ---------------------------------------------------------------------------

def load_demo_data() -> pd.DataFrame:
    """
    Load the preprocessed synthetic/real Delhi heat stress dataset.

    Falls back to generating synthetic data on-the-fly if CSV is missing.

    Returns
    -------
    pd.DataFrame with all feature columns
    """
    if os.path.exists(DEMO_CSV_PATH):
        logger.info(f"Loading demo data from {DEMO_CSV_PATH}")
        df = pd.read_csv(DEMO_CSV_PATH)
    else:
        logger.warning("Demo CSV not found — generating synthetic data on-the-fly")
        # Import here to avoid circular imports at module level
        from src.preprocessing import generate_delhi_demo_data
        df = generate_delhi_demo_data(n_points=8000)
    return df


def load_hotspot_zones() -> pd.DataFrame:
    """
    Load the hotspot zone summary CSV.

    Returns
    -------
    pd.DataFrame with hotspot zone statistics
    """
    if os.path.exists(HOTSPOT_CSV_PATH):
        df = pd.read_csv(HOTSPOT_CSV_PATH)
        logger.info(f"Loaded {len(df)} hotspot zones from {HOTSPOT_CSV_PATH}")
        return df

    logger.warning("Hotspot CSV not found — returning empty DataFrame")
    return pd.DataFrame()


def load_hotspot_geojson() -> Optional[dict]:
    """Load hotspot zones as GeoJSON dict."""
    if os.path.exists(HOTSPOT_GEOJSON_PATH):
        with open(HOTSPOT_GEOJSON_PATH, "r") as f:
            return json.load(f)
    return None


def load_rf_model() -> Optional[Dict]:
    """Load Random Forest model bundle from disk."""
    if os.path.exists(RF_MODEL_PATH):
        bundle = joblib.load(RF_MODEL_PATH)
        logger.info("RF model loaded successfully")
        return bundle
    logger.warning(f"RF model not found at {RF_MODEL_PATH}")
    return None


def load_gb_model() -> Optional[Dict]:
    """Load Gradient Boosting model bundle from disk."""
    if os.path.exists(GB_MODEL_PATH):
        bundle = joblib.load(GB_MODEL_PATH)
        logger.info("GB model loaded successfully")
        return bundle
    logger.warning(f"GB model not found at {GB_MODEL_PATH}")
    return None


# ---------------------------------------------------------------------------
# Derived statistics
# ---------------------------------------------------------------------------

def get_city_stats(df: pd.DataFrame) -> Dict:
    """
    Compute dashboard summary statistics from the main DataFrame.

    Returns
    -------
    dict with display-ready statistics
    """
    zone_counts = df["heat_zone"].value_counts()
    total = len(df)
    lu_counts = df["land_use"].value_counts()

    return {
        # Temperature
        "mean_lst": round(df["LST"].mean(), 1),
        "max_lst": round(df["LST"].max(), 1),
        "min_lst": round(df["LST"].min(), 1),
        "std_lst": round(df["LST"].std(), 1),
        # Heat zones
        "extreme_count": int(zone_counts.get("Extreme", 0)),
        "high_count": int(zone_counts.get("High", 0)),
        "extreme_pct": round(100 * zone_counts.get("Extreme", 0) / total, 1),
        "high_pct": round(100 * zone_counts.get("High", 0) / total, 1),
        # Population at risk (extreme + high zones)
        "pop_at_risk": int(
            df[df["heat_zone"].isin(["Extreme", "High"])]["pop_density"].sum()
        ),
        "total_pop": int(df["pop_density"].sum()),
        # Vegetation & built-up
        "mean_ndvi": round(df["NDVI"].mean(), 3),
        "mean_ndbi": round(df["NDBI"].mean(), 3),
        "green_cover_pct": round(100 * (df["NDVI"] > 0.3).mean(), 1),
        # Land use
        "dominant_land_use": lu_counts.index[0] if len(lu_counts) > 0 else "N/A",
        # Spatial extent
        "lat_center": round(df["lat"].mean(), 4),
        "lon_center": round(df["lon"].mean(), 4),
        "n_points": total,
        "city": "Delhi",
        "data_year": 2023,
    }


def get_land_use_lst_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute mean/max LST grouped by land use type.

    Returns
    -------
    pd.DataFrame with columns: land_use, mean_LST, max_LST, count, pct
    """
    grouped = (
        df.groupby("land_use")
        .agg(
            mean_LST=("LST", "mean"),
            max_LST=("LST", "max"),
            min_LST=("LST", "min"),
            count=("LST", "count"),
            mean_NDVI=("NDVI", "mean"),
            mean_pop=("pop_density", "mean"),
        )
        .reset_index()
    )
    grouped["mean_LST"] = grouped["mean_LST"].round(2)
    grouped["max_LST"] = grouped["max_LST"].round(2)
    grouped["min_LST"] = grouped["min_LST"].round(2)
    grouped["mean_NDVI"] = grouped["mean_NDVI"].round(4)
    grouped["mean_pop"] = grouped["mean_pop"].round(0).astype(int)
    grouped["pct"] = (100 * grouped["count"] / len(df)).round(1)
    return grouped.sort_values("mean_LST", ascending=False)


def get_heat_zone_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """Distribution of heat zones as counts and percentages."""
    counts = df["heat_zone"].value_counts()
    order = ["Extreme", "High", "Moderate", "Low", "Very Low"]
    out = pd.DataFrame({
        "heat_zone": order,
        "count": [int(counts.get(z, 0)) for z in order],
        "pct": [round(100 * counts.get(z, 0) / len(df), 1) for z in order],
        "color": ["#F44336", "#FF9800", "#FFEB3B", "#4CAF50", "#2196F3"],
    })
    return out


def prepare_download_csv(df: pd.DataFrame) -> str:
    """Convert DataFrame to CSV string for Streamlit download button."""
    return df.to_csv(index=False)
