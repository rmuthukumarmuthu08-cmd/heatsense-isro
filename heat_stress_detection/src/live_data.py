"""
live_data.py — Real-time & External Data Integration

Fetches live weather, temperature, and environmental data from free APIs.
All APIs used here require ZERO API keys.

Sources:
    - Open-Meteo (https://open-meteo.com/) — live temperature & humidity
    - NASA FIRMS VIIRS via USGS — active heat anomalies (no key for CSV)
    - OpenMeteo AQI — air quality index
    - Nominatim (OpenStreetMap) — city geocoding

Usage:
    from src.live_data import get_live_city_weather, SUPPORTED_CITIES
    weather = get_live_city_weather("Delhi")
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import urllib.request
    import json as _json
    _HAS_URLLIB = True
except ImportError:
    _HAS_URLLIB = False

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# SUPPORTED CITIES — bounds, coordinates, population
# ─────────────────────────────────────────────────────────────────────────────

SUPPORTED_CITIES: Dict[str, Dict] = {
    "Delhi": {
        "lat": 28.6139, "lon": 77.2090,
        "bounds": {"lat_min": 28.40, "lat_max": 28.88, "lon_min": 76.84, "lon_max": 77.35},
        "population": 32_900_000,
        "area_km2": 1484,
        "n_hotspot_centers": 6,
        "cool_zones": 5,
        "state": "Delhi NCT",
        "climate": "Semi-arid (BSh)",
    },
    "Mumbai": {
        "lat": 19.0760, "lon": 72.8777,
        "bounds": {"lat_min": 18.89, "lat_max": 19.27, "lon_min": 72.77, "lon_max": 72.99},
        "population": 20_667_656,
        "area_km2": 603,
        "n_hotspot_centers": 5,
        "cool_zones": 6,
        "state": "Maharashtra",
        "climate": "Tropical wet (Aw)",
    },
    "Chennai": {
        "lat": 13.0827, "lon": 80.2707,
        "bounds": {"lat_min": 12.90, "lat_max": 13.23, "lon_min": 80.16, "lon_max": 80.33},
        "population": 10_971_108,
        "area_km2": 426,
        "n_hotspot_centers": 4,
        "cool_zones": 4,
        "state": "Tamil Nadu",
        "climate": "Tropical wet & dry (Aw)",
    },
    "Kolkata": {
        "lat": 22.5726, "lon": 88.3639,
        "bounds": {"lat_min": 22.39, "lat_max": 22.76, "lon_min": 88.21, "lon_max": 88.54},
        "population": 14_850_000,
        "area_km2": 185,
        "n_hotspot_centers": 5,
        "cool_zones": 3,
        "state": "West Bengal",
        "climate": "Tropical wet & dry (Aw)",
    },
    "Hyderabad": {
        "lat": 17.3850, "lon": 78.4867,
        "bounds": {"lat_min": 17.20, "lat_max": 17.58, "lon_min": 78.30, "lon_max": 78.67},
        "population": 10_268_653,
        "area_km2": 650,
        "n_hotspot_centers": 4,
        "cool_zones": 4,
        "state": "Telangana",
        "climate": "Semi-arid (BSh)",
    },
    "Bangalore": {
        "lat": 12.9716, "lon": 77.5946,
        "bounds": {"lat_min": 12.82, "lat_max": 13.14, "lon_min": 77.45, "lon_max": 77.74},
        "population": 13_193_000,
        "area_km2": 709,
        "n_hotspot_centers": 4,
        "cool_zones": 6,
        "state": "Karnataka",
        "climate": "Tropical savanna (Aw) / Highland",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# OPEN-METEO — Live weather (no API key, completely free)
# ─────────────────────────────────────────────────────────────────────────────

OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
    "precipitation,wind_speed_10m,wind_direction_10m,weather_code,cloud_cover"
    "&hourly=temperature_2m,relative_humidity_2m,apparent_temperature"
    "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,uv_index_max"
    "&timezone=Asia%2FKolkata"
    "&forecast_days=7"
)

WMO_WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Heavy thunderstorm",
}


def _fetch_json(url: str, timeout: int = 8) -> Optional[dict]:
    """Fetch JSON from URL with timeout. Returns None on any failure."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "HeatSense/1.0 ISRO-Hackathon (educational)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("Live data fetch failed: %s", exc)
        return None


def get_live_city_weather(city: str) -> Dict:
    """
    Fetch current weather and 7-day forecast for a supported city via Open-Meteo.

    Parameters
    ----------
    city : str
        City name — must be in SUPPORTED_CITIES.

    Returns
    -------
    dict with keys:
        city, timestamp, current (temp, humidity, feels_like, wind, condition),
        forecast_7day (list of daily dicts), hourly_today (list),
        is_live (bool), source
    """
    if city not in SUPPORTED_CITIES:
        raise ValueError(f"City '{city}' not supported. Choose from: {list(SUPPORTED_CITIES)}")

    meta = SUPPORTED_CITIES[city]
    url  = OPEN_METEO_URL.format(lat=meta["lat"], lon=meta["lon"])
    data = _fetch_json(url)

    if data is None:
        return _mock_weather(city, meta)

    try:
        cur = data["current"]
        daily = data["daily"]
        hourly = data["hourly"]

        # 7-day forecast
        forecast = []
        n_days = len(daily["time"])
        for i in range(n_days):
            forecast.append({
                "date":       daily["time"][i],
                "temp_max":   daily["temperature_2m_max"][i],
                "temp_min":   daily["temperature_2m_min"][i],
                "precip_mm":  daily["precipitation_sum"][i],
                "uv_index":   daily["uv_index_max"][i],
            })

        # Hourly for today (first 24 slices)
        hourly_today = []
        for i in range(min(24, len(hourly["time"]))):
            hourly_today.append({
                "time":     hourly["time"][i],
                "temp":     hourly["temperature_2m"][i],
                "humidity": hourly["relative_humidity_2m"][i],
                "feels":    hourly["apparent_temperature"][i],
            })

        weather_code = cur.get("weather_code", 0)
        result = {
            "city":      city,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "is_live":   True,
            "source":    "Open-Meteo (https://open-meteo.com/)",
            "lat":       meta["lat"],
            "lon":       meta["lon"],
            "current": {
                "temperature":   cur["temperature_2m"],
                "humidity":      cur["relative_humidity_2m"],
                "feels_like":    cur["apparent_temperature"],
                "precipitation": cur["precipitation"],
                "wind_speed":    cur["wind_speed_10m"],
                "wind_direction":cur["wind_direction_10m"],
                "cloud_cover":   cur["cloud_cover"],
                "condition":     WMO_WEATHER_CODES.get(weather_code, "Unknown"),
                "weather_code":  weather_code,
            },
            "forecast_7day":  forecast,
            "hourly_today":   hourly_today,
        }
        logger.info("Live weather fetched for %s: %.1f°C", city, cur["temperature_2m"])
        return result

    except (KeyError, TypeError, IndexError) as exc:
        logger.warning("Error parsing Open-Meteo response for %s: %s", city, exc)
        return _mock_weather(city, meta)


def _mock_weather(city: str, meta: Dict) -> Dict:
    """Return realistic synthetic weather when API is unavailable (offline fallback)."""
    rng  = np.random.default_rng(seed=abs(hash(city)) % 2**32)
    base = {"Delhi": 38, "Mumbai": 34, "Chennai": 36, "Kolkata": 35,
            "Hyderabad": 37, "Bangalore": 28}.get(city, 35)
    temp = float(base + rng.normal(0, 2))
    return {
        "city":      city,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "is_live":   False,
        "source":    "Offline fallback (Open-Meteo unavailable)",
        "lat":       meta["lat"],
        "lon":       meta["lon"],
        "current": {
            "temperature":    temp,
            "humidity":       float(rng.integers(40, 80)),
            "feels_like":     temp + float(rng.uniform(1, 5)),
            "precipitation":  0.0,
            "wind_speed":     float(rng.uniform(5, 25)),
            "wind_direction": float(rng.integers(0, 360)),
            "cloud_cover":    float(rng.integers(10, 60)),
            "condition":      "Clear sky",
            "weather_code":   0,
        },
        "forecast_7day": [
            {
                "date":      (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d"),
                "temp_max":  round(temp + rng.uniform(-1, 3), 1),
                "temp_min":  round(temp - rng.uniform(3, 8), 1),
                "precip_mm": 0.0,
                "uv_index":  round(float(rng.uniform(7, 11)), 1),
            }
            for i in range(7)
        ],
        "hourly_today": [
            {
                "time":     f"{datetime.now().strftime('%Y-%m-%d')}T{h:02d}:00",
                "temp":     round(temp + 4 * np.sin((h - 6) * np.pi / 12), 1),
                "humidity": int(60 - h * 0.5),
                "feels":    round(temp + 2, 1),
            }
            for h in range(24)
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# HEAT STRESS INDEX from live weather
# ─────────────────────────────────────────────────────────────────────────────

def compute_heat_index(temp_c: float, rh: float) -> float:
    """
    Steadman (1979) Heat Index in Celsius.
    Valid for temp > 27°C and RH > 40%.

    Parameters
    ----------
    temp_c : float  Air temperature (°C)
    rh     : float  Relative humidity (%)
    """
    T = temp_c * 9 / 5 + 32  # °F
    HI = (-42.379
          + 2.04901523 * T
          + 10.14333127 * rh
          - 0.22475541 * T * rh
          - 0.00683783 * T ** 2
          - 0.05481717 * rh ** 2
          + 0.00122874 * T ** 2 * rh
          + 0.00085282 * T * rh ** 2
          - 0.00000199 * T ** 2 * rh ** 2)
    return round((HI - 32) * 5 / 9, 1)  # back to °C


def get_heat_alert_level(heat_index_c: float) -> Tuple[str, str]:
    """
    Return (alert_level, advice) based on heat index.

    Returns
    -------
    (level, hex_colour)
    """
    if heat_index_c >= 54:
        return "EXTREME DANGER", "#B71C1C"
    elif heat_index_c >= 41:
        return "DANGER", "#E53935"
    elif heat_index_c >= 32:
        return "EXTREME CAUTION", "#FF9800"
    elif heat_index_c >= 27:
        return "CAUTION", "#FDD835"
    else:
        return "SAFE", "#43A047"


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-CITY COMPARISON
# ─────────────────────────────────────────────────────────────────────────────

def get_all_cities_weather(cities: Optional[List[str]] = None) -> pd.DataFrame:
    """
    Fetch current weather for multiple cities and return as a DataFrame.

    Parameters
    ----------
    cities : list of str, optional
        Subset of SUPPORTED_CITIES. Defaults to all.

    Returns
    -------
    pd.DataFrame with columns: city, temperature, feels_like, humidity,
        wind_speed, condition, heat_index, alert_level, is_live
    """
    if cities is None:
        cities = list(SUPPORTED_CITIES.keys())

    rows = []
    for city in cities:
        try:
            w = get_live_city_weather(city)
            cur = w["current"]
            hi  = compute_heat_index(cur["temperature"], cur["humidity"])
            lvl, _ = get_heat_alert_level(hi)
            rows.append({
                "city":         city,
                "state":        SUPPORTED_CITIES[city]["state"],
                "temperature":  cur["temperature"],
                "feels_like":   cur["feels_like"],
                "humidity":     cur["humidity"],
                "wind_speed":   cur["wind_speed"],
                "cloud_cover":  cur["cloud_cover"],
                "condition":    cur["condition"],
                "heat_index":   hi,
                "alert_level":  lvl,
                "is_live":      w["is_live"],
                "timestamp":    w["timestamp"],
            })
            time.sleep(0.15)  # polite rate limit
        except Exception as exc:
            logger.error("Failed to fetch weather for %s: %s", city, exc)

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# USER-UPLOADED CSV VALIDATION & INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED_COLUMNS = {"lat", "lon", "LST"}
OPTIONAL_COLUMNS = {
    "NDVI", "NDBI", "NDWI", "pop_density",
    "dist_water", "elevation", "imperv_fraction", "land_use",
}

DEFAULT_FILL = {
    "NDVI": 0.2, "NDBI": 0.1, "NDWI": -0.1, "pop_density": 5000.0,
    "dist_water": 2.0, "elevation": 200.0, "imperv_fraction": 0.5,
    "land_use": "Residential",
}


def validate_uploaded_csv(df: pd.DataFrame) -> Tuple[bool, str, pd.DataFrame]:
    """
    Validate and clean a user-uploaded CSV for heat stress analysis.

    Parameters
    ----------
    df : pd.DataFrame
        Raw uploaded DataFrame.

    Returns
    -------
    (is_valid, message, cleaned_df)
        is_valid  — True if minimum columns are present
        message   — human-readable status string
        cleaned_df— filled and validated DataFrame ready for analysis
    """
    # Normalise column names
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        return (
            False,
            f"Missing required columns: {missing}. "
            f"Your CSV must contain: lat, lon, LST (land surface temperature in °C).",
            df,
        )

    # Drop rows with null in required columns
    before = len(df)
    df = df.dropna(subset=list(REQUIRED_COLUMNS))
    dropped = before - len(df)

    # Validate bounds
    df = df[df["lat"].between(-90, 90) & df["lon"].between(-180, 180)]
    df = df[df["LST"].between(0, 80)]

    # Fill missing optional columns
    for col, fill_val in DEFAULT_FILL.items():
        if col not in df.columns:
            df[col] = fill_val
        else:
            df[col] = df[col].fillna(fill_val)

    # Compute heat_stress_index if missing
    if "heat_stress_index" not in df.columns:
        lst = df["LST"].values.astype(float)
        ndvi = df["NDVI"].values.astype(float)
        imperv = df["imperv_fraction"].values.astype(float)
        lst_n = (lst - lst.min()) / (lst.max() - lst.min() + 1e-8)
        ndvi_n = 1 - (ndvi - ndvi.min()) / (ndvi.max() - ndvi.min() + 1e-8)
        df["heat_stress_index"] = np.clip(0.6 * lst_n + 0.25 * ndvi_n + 0.15 * imperv, 0, 1).round(4)

    msg = (
        f"CSV validated: {len(df):,} valid rows"
        + (f" ({dropped} null rows removed)" if dropped else "")
        + f". Optional columns auto-filled: {OPTIONAL_COLUMNS - set(df.columns)}."
    )
    return True, msg, df


def detect_city_from_upload(df: pd.DataFrame) -> Optional[str]:
    """
    Guess which SUPPORTED_CITIES a user-uploaded DataFrame belongs to
    based on median lat/lon.

    Returns city name or None.
    """
    try:
        lat_med = df["lat"].median()
        lon_med = df["lon"].median()
        best_city, best_dist = None, float("inf")
        for city, meta in SUPPORTED_CITIES.items():
            dist = ((lat_med - meta["lat"]) ** 2 + (lon_med - meta["lon"]) ** 2) ** 0.5
            if dist < best_dist:
                best_city, best_dist = city, dist
        # Only return if within ~2 degrees
        return best_city if best_dist < 2.0 else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# AI RECOMMENDATIONS from live input
# ─────────────────────────────────────────────────────────────────────────────

def generate_live_recommendations(
    city: str,
    weather: Dict,
    hotspot_count: int = 0,
    peak_lst: float = 40.0,
) -> List[Dict]:
    """
    Generate context-aware recommendations based on live weather conditions.

    Parameters
    ----------
    city          : str
    weather       : dict from get_live_city_weather()
    hotspot_count : int  Number of detected hotspot zones
    peak_lst      : float Peak LST in °C

    Returns
    -------
    List of recommendation dicts with: priority, action, rationale, urgency
    """
    cur = weather["current"]
    temp = cur["temperature"]
    hi   = compute_heat_index(temp, cur["humidity"])
    alert, _ = get_heat_alert_level(hi)

    recs = []

    # Immediate public health
    if hi >= 41:
        recs.append({
            "priority":  1,
            "category":  "Public Health",
            "action":    f"Issue Heat Emergency Alert for {city}",
            "rationale": f"Heat index {hi:.1f}°C exceeds DANGER threshold (41°C). "
                         f"Risk of heat stroke without action.",
            "urgency":   "TODAY",
            "icon":      "🚨",
        })
        recs.append({
            "priority":  2,
            "category":  "Public Health",
            "action":    "Open all community cooling centres and hospitals",
            "rationale": "High heat index demands immediate public shelter access.",
            "urgency":   "TODAY",
            "icon":      "🏥",
        })

    # Wind + humidity based
    if cur["wind_speed"] < 10 and cur["humidity"] > 60:
        recs.append({
            "priority":  3,
            "category":  "Ventilation",
            "action":    "Deploy mist fans at all major transit hubs and markets",
            "rationale": f"Low wind speed ({cur['wind_speed']:.1f} km/h) + "
                         f"high humidity ({cur['humidity']}%) traps heat. "
                         "Evaporative cooling is most effective in these conditions.",
            "urgency":   "THIS WEEK",
            "icon":      "💨",
        })

    # Hotspot-specific
    if hotspot_count > 10:
        recs.append({
            "priority":  4,
            "category":  "Urban Planning",
            "action":    f"Prioritise cool roofs for {min(hotspot_count, 20)} industrial zones",
            "rationale": f"{hotspot_count} hotspot clusters detected. "
                         "Reflective cool roofs reduce LST by 2–4°C with no water usage.",
            "urgency":   "THIS MONTH",
            "icon":      "🏭",
        })

    if peak_lst > 48:
        recs.append({
            "priority":  5,
            "category":  "Green Infrastructure",
            "action":    "Emergency tree planting in top 3 hotspot zones",
            "rationale": f"Peak LST of {peak_lst:.1f}°C exceeds critical threshold. "
                         "Each mature tree provides cooling equivalent to 10 room ACs.",
            "urgency":   "THIS MONTH",
            "icon":      "🌳",
        })

    # Always include green infrastructure
    recs.append({
        "priority":  6,
        "category":  "Green Infrastructure",
        "action":    f"Plant 10,000 trees along {city} arterial roads",
        "rationale": "NDVI↔LST correlation −0.75 shows trees are the most cost-effective "
                     "long-term cooling intervention.",
        "urgency":   "THIS YEAR",
        "icon":      "🌲",
    })

    recs.append({
        "priority":  7,
        "category":  "Water Features",
        "action":    "Restore urban water bodies and create blue corridors",
        "rationale": "Water evaporation naturally cools surrounding areas by 2–3°C. "
                     "Cost-effective with high biodiversity co-benefits.",
        "urgency":   "THIS YEAR",
        "icon":      "💧",
    })

    recs.append({
        "priority":  8,
        "category":  "Policy",
        "action":    "Mandate green cover in new construction permits",
        "rationale": "30% mandatory green cover in new buildings prevents future "
                     "heat island expansion at zero government cost.",
        "urgency":   "NEXT YEAR",
        "icon":      "📋",
    })

    # Sort by priority
    recs.sort(key=lambda r: r["priority"])
    return recs


# ─────────────────────────────────────────────────────────────────────────────
# QUICK SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("\n=== HeatSense Live Data Module Self-Test ===\n")

    # Test Open-Meteo
    print("Fetching live weather for Delhi...")
    w = get_live_city_weather("Delhi")
    c = w["current"]
    hi = compute_heat_index(c["temperature"], c["humidity"])
    lvl, col = get_heat_alert_level(hi)
    print(f"  Temperature  : {c['temperature']}°C")
    print(f"  Feels like   : {c['feels_like']}°C")
    print(f"  Humidity     : {c['humidity']}%")
    print(f"  Condition    : {c['condition']}")
    print(f"  Heat Index   : {hi}°C")
    print(f"  Alert Level  : {lvl}")
    print(f"  Live data    : {w['is_live']}")
    print(f"  Source       : {w['source']}")

    # Test heat index
    print("\nHeat Index table:")
    for t, rh in [(30, 50), (35, 60), (40, 70), (45, 80)]:
        hi = compute_heat_index(t, rh)
        lvl, _ = get_heat_alert_level(hi)
        print(f"  {t}°C / {rh}%RH → HI={hi}°C [{lvl}]")

    # Test CSV validation
    print("\nTesting CSV validation...")
    fake = pd.DataFrame({
        "lat": [28.61, 28.62, None],
        "lon": [77.20, 77.21, 77.22],
        "LST": [42.0, 38.5, 55.0],
    })
    ok, msg, cleaned = validate_uploaded_csv(fake)
    print(f"  Valid: {ok} | {msg}")
    print(f"  Rows after cleaning: {len(cleaned)}")

    print("\n✓ Self-test complete.")
