"""
lst_calculator.py — Land Surface Temperature (LST) Calculation Engine

Purpose:
    Implements the complete 5-step radiative transfer equation to derive LST
    from Landsat Band 10 thermal infrared data, plus UHI index computation
    and heat zone classification.

Algorithm Reference:
    Jiménez-Muñoz & Sobrino (2003) — Generalized Single-Channel Method
    Landsat 8 Collection 2 Data Format Control Book — USGS

Inputs:
    Band 10 DN values, MTL metadata (gain/offset, K1/K2 constants),
    Band 4 & 5 reflectance for NDVI

Outputs:
    LST raster (°C), UHI index, 5-class heat zone raster

Complexity:  O(n) — pure vectorised NumPy operations
Advantages:  Physically-based, internationally validated method
Limitations: Assumes clear-sky conditions; errors ±1-2°C vs ground truth
"""

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Landsat 8/9 Band 10 physical constants
# ---------------------------------------------------------------------------
K1_BAND10 = 774.8853   # W/(m²·sr·µm)
K2_BAND10 = 1321.0789  # K
LAMBDA_BAND10 = 10.895e-6   # Band 10 central wavelength in metres
RHO = 1.438e-2          # h·c/σ in metre·Kelvin (Planck constant × speed of light / Boltzmann)

# NDVI thresholds for emissivity calculation
NDVI_SOIL = 0.2    # Bare soil / built-up
NDVI_VEG = 0.5     # Full vegetation canopy


# ---------------------------------------------------------------------------
# Step 1 — DN to Spectral Radiance
# ---------------------------------------------------------------------------

def dn_to_radiance(dn: np.ndarray, mult: float, add: float) -> np.ndarray:
    """
    Convert raw Digital Number (DN) to Spectral Radiance.

    Formula: L_λ = ML × Qcal + AL
        ML  = RADIANCE_MULT_BAND_10  (from MTL file)
        AL  = RADIANCE_ADD_BAND_10
        Qcal = raw DN pixel value

    Parameters
    ----------
    dn   : raw DN array from Band 10
    mult : RADIANCE_MULT_BAND_10 constant from MTL metadata
    add  : RADIANCE_ADD_BAND_10 constant from MTL metadata

    Returns
    -------
    np.ndarray — Spectral radiance in W/(m²·sr·µm)
    """
    radiance = mult * dn.astype(float) + add
    logger.debug(f"Radiance range: {radiance.min():.3f} – {radiance.max():.3f} W/(m²·sr·µm)")
    return radiance


# ---------------------------------------------------------------------------
# Step 2 — Radiance to Brightness Temperature
# ---------------------------------------------------------------------------

def radiance_to_bt(radiance: np.ndarray,
                   k1: float = K1_BAND10,
                   k2: float = K2_BAND10) -> np.ndarray:
    """
    Convert spectral radiance to Brightness Temperature (BT) in Celsius.

    Formula: BT = K2 / ln(K1/L + 1) − 273.15

    Parameters
    ----------
    radiance : spectral radiance array
    k1, k2   : calibration constants (Landsat Band 10 defaults)

    Returns
    -------
    np.ndarray — Brightness Temperature in °C
    """
    # Avoid division by zero or log of negative
    safe_radiance = np.where(radiance > 0, radiance, np.nan)
    bt_kelvin = k2 / np.log(k1 / safe_radiance + 1.0)
    bt_celsius = bt_kelvin - 273.15
    logger.debug(f"BT range: {np.nanmin(bt_celsius):.2f} – {np.nanmax(bt_celsius):.2f} °C")
    return bt_celsius


# ---------------------------------------------------------------------------
# Step 3 — NDVI from Bands 4 & 5
# ---------------------------------------------------------------------------

def calculate_ndvi(red: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """
    Normalised Difference Vegetation Index.

    Formula: NDVI = (NIR − Red) / (NIR + Red)
              = (Band5 − Band4) / (Band5 + Band4)

    Range: −1 to +1  |  Vegetation > 0.2  |  Water < 0  |  Bare soil 0.1–0.2

    Parameters
    ----------
    red : Band 4 reflectance (0–1)
    nir : Band 5 reflectance (0–1)

    Returns
    -------
    np.ndarray — NDVI values clipped to [−1, +1]
    """
    denominator = nir + red
    denominator = np.where(denominator == 0, np.nan, denominator)
    ndvi = (nir - red) / denominator
    return np.clip(ndvi, -1.0, 1.0)


def calculate_ndbi(nir: np.ndarray, swir: np.ndarray) -> np.ndarray:
    """
    Normalised Difference Built-up Index.
    Formula: NDBI = (SWIR − NIR) / (SWIR + NIR)
    High values indicate urban/built-up areas.
    """
    denominator = swir + nir
    denominator = np.where(denominator == 0, np.nan, denominator)
    return np.clip((swir - nir) / denominator, -1.0, 1.0)


def calculate_ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """
    Normalised Difference Water Index (McFeeters 1996).
    Formula: NDWI = (Green − NIR) / (Green + NIR)
    Positive values indicate water bodies.
    """
    denominator = green + nir
    denominator = np.where(denominator == 0, np.nan, denominator)
    return np.clip((green - nir) / denominator, -1.0, 1.0)


# ---------------------------------------------------------------------------
# Step 4 — Land Surface Emissivity from NDVI
# ---------------------------------------------------------------------------

def calculate_lse(ndvi: np.ndarray,
                  ndvi_s: float = NDVI_SOIL,
                  ndvi_v: float = NDVI_VEG) -> np.ndarray:
    """
    Calculate Land Surface Emissivity (LSE) using the NDVI Threshold Method.

    Formula:
        Pv  = ((NDVI − NDVIs) / (NDVIv − NDVIs))²   ← fractional vegetation
        LSE = 0.004 × Pv + 0.986

    Special cases:
        NDVI < NDVIs (bare soil) → LSE = 0.97
        NDVI > NDVIv (full veg)  → LSE = 0.99
        NDVIs ≤ NDVI ≤ NDVIv     → mixed pixel formula

    Parameters
    ----------
    ndvi   : NDVI array
    ndvi_s : NDVI threshold for bare soil (default 0.2)
    ndvi_v : NDVI threshold for full vegetation (default 0.5)

    Returns
    -------
    np.ndarray — Emissivity values (0.97–0.99)
    """
    # Fractional vegetation cover
    pv = ((ndvi - ndvi_s) / (ndvi_v - ndvi_s)) ** 2
    pv = np.clip(pv, 0.0, 1.0)

    # Mixed pixel emissivity
    lse_mixed = 0.004 * pv + 0.986

    # Override for bare soil and full vegetation
    lse = np.where(ndvi < ndvi_s, 0.97,
                   np.where(ndvi > ndvi_v, 0.99, lse_mixed))
    logger.debug(f"LSE range: {lse.min():.4f} – {lse.max():.4f}")
    return lse


# ---------------------------------------------------------------------------
# Step 5 — Final LST from BT and LSE
# ---------------------------------------------------------------------------

def calculate_lst(bt: np.ndarray,
                  lse: np.ndarray,
                  wavelength: float = LAMBDA_BAND10,
                  rho: float = RHO) -> np.ndarray:
    """
    Calculate Land Surface Temperature (LST) from Brightness Temperature and Emissivity.

    Formula: LST = BT / (1 + (λ × BT / ρ) × ln(ε))
        λ   = 10.895 µm (Band 10 wavelength)
        ρ   = h·c/σ = 0.01438 m·K
        ε   = Land Surface Emissivity

    Parameters
    ----------
    bt         : Brightness Temperature in °C
    lse        : Land Surface Emissivity
    wavelength : Band central wavelength in metres
    rho        : Planck radiation constant derivative (m·K)

    Returns
    -------
    np.ndarray — True surface temperature in °C
    """
    bt_kelvin = bt + 273.15
    ln_epsilon = np.log(lse)
    lst_kelvin = bt_kelvin / (1.0 + (wavelength * bt_kelvin / rho) * ln_epsilon)
    lst_celsius = lst_kelvin - 273.15
    logger.info(f"LST range: {np.nanmin(lst_celsius):.2f} – {np.nanmax(lst_celsius):.2f} °C")
    return lst_celsius


# ---------------------------------------------------------------------------
# UHI Index and Classification
# ---------------------------------------------------------------------------

def calculate_uhi_index(lst: np.ndarray) -> np.ndarray:
    """
    Calculate Urban Heat Island (UHI) index — normalised deviation from city mean.

    Formula: UHI = (LST_pixel − LST_mean) / LST_std

    Returns
    -------
    np.ndarray — Standardised UHI scores (z-scores)
    """
    mean = np.nanmean(lst)
    std = np.nanstd(lst)
    if std == 0:
        return np.zeros_like(lst)
    uhi = (lst - mean) / std
    logger.info(f"UHI index: mean={mean:.2f}°C, std={std:.2f}°C | range {uhi.min():.2f}–{uhi.max():.2f}")
    return uhi


def classify_heat_zones(uhi: np.ndarray) -> np.ndarray:
    """
    Classify UHI index into 5 ordinal heat zones.

    Thresholds:
        UHI < -1.5             → Very Low Heat Zone
        -1.5 ≤ UHI < -0.5     → Low Heat Zone
        -0.5 ≤ UHI <  0.5     → Moderate Heat Zone
         0.5 ≤ UHI <  1.5     → High Heat Zone
        UHI ≥  1.5             → Extreme Heat Zone (HOTSPOT)

    Returns
    -------
    np.ndarray of str labels
    """
    conditions = [
        uhi < -1.5,
        (uhi >= -1.5) & (uhi < -0.5),
        (uhi >= -0.5) & (uhi < 0.5),
        (uhi >= 0.5) & (uhi < 1.5),
        uhi >= 1.5,
    ]
    labels = ["Very Low", "Low", "Moderate", "High", "Extreme"]
    return np.select(conditions, labels, default="Moderate")


def compute_full_lst_pipeline(df: pd.DataFrame) -> pd.DataFrame:
    """
    Run UHI index + heat zone classification on an existing DataFrame
    that already has 'LST' column (e.g., synthetic or pre-processed data).

    Parameters
    ----------
    df : DataFrame with 'LST' column

    Returns
    -------
    DataFrame with added 'UHI_index' and 'heat_zone' columns
    """
    df = df.copy()
    df["UHI_index"] = calculate_uhi_index(df["LST"].values)
    df["heat_zone"] = classify_heat_zones(df["UHI_index"].values)
    return df


def get_lst_statistics(df: pd.DataFrame) -> dict:
    """
    Compute summary statistics for LST values across the study area.

    Returns
    -------
    dict with keys: mean, max, min, std, extreme_pct, high_pct
    """
    lst = df["LST"].values
    zone_counts = df["heat_zone"].value_counts()
    total = len(df)

    return {
        "mean_lst": round(float(np.nanmean(lst)), 2),
        "max_lst": round(float(np.nanmax(lst)), 2),
        "min_lst": round(float(np.nanmin(lst)), 2),
        "std_lst": round(float(np.nanstd(lst)), 2),
        "extreme_pct": round(100 * zone_counts.get("Extreme", 0) / total, 1),
        "high_pct": round(100 * zone_counts.get("High", 0) / total, 1),
        "moderate_pct": round(100 * zone_counts.get("Moderate", 0) / total, 1),
        "low_pct": round(100 * zone_counts.get("Low", 0) / total, 1),
        "very_low_pct": round(100 * zone_counts.get("Very Low", 0) / total, 1),
    }
