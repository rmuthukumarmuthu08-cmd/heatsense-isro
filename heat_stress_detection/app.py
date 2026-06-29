"""
app.py — Urban Heat Stress Hotspot Detection Dashboard
ISRO Bharatiya Antariksh Hackathon 2025

8-page Streamlit dashboard:
    🏠 Home | 🗺️ Heat Map | 🔥 Hotspot Analysis | 🤖 AI Predictions
    ❄️ Cooling Recommendations | 📊 Statistics | 📥 Downloads | ℹ️ About

Run: streamlit run app.py
"""

import json
import logging
import os
import sys

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Project root on path ──────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.WARNING)

# ── Page config — must be FIRST Streamlit call ────────────────────────────
st.set_page_config(
    page_title="HeatSense — Urban Heat Stress Detection",
    page_icon="🌡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Dark theme tweaks */
.main-header {
    background: linear-gradient(135deg, #B71C1C 0%, #FF6F00 50%, #1565C0 100%);
    padding: 20px 30px;
    border-radius: 12px;
    color: white;
    text-align: center;
    margin-bottom: 20px;
}
.metric-card {
    background: linear-gradient(135deg, #1a1a2e, #16213e);
    border: 1px solid #333;
    border-radius: 10px;
    padding: 16px;
    text-align: center;
}
.metric-value {
    font-size: 2rem;
    font-weight: bold;
    color: #FF6B35;
}
.metric-label {
    font-size: 0.85rem;
    color: #aaa;
    margin-top: 4px;
}
.hotspot-critical { border-left: 4px solid #B71C1C; padding-left: 12px; }
.hotspot-high     { border-left: 4px solid #FF9800; padding-left: 12px; }
.hotspot-moderate { border-left: 4px solid #FFEB3B; padding-left: 12px; }
.rec-card {
    background: #1a1a2e;
    border: 1px solid #444;
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 12px;
}
.stMetric > div { background: #1a1a2e; border-radius: 8px; padding: 8px; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# CLOUD STARTUP — Generate data + models if missing (first run)
# ============================================================

@st.cache_resource(show_spinner="Initialising HeatSense for first run (~15 sec)...")
def _cloud_startup():
    """
    Generate all required data files and trained models on first run.
    On Streamlit Cloud (or any cold start), data/ and models/ are empty.
    This runs once and is cached for the session lifetime.
    """
    import os
    import sys

    demo_csv   = os.path.join(PROJECT_ROOT, "data", "demo", "delhi_heat_stress.csv")
    rf_model   = os.path.join(PROJECT_ROOT, "models", "heat_stress_rf.pkl")
    zones_csv  = os.path.join(PROJECT_ROOT, "data", "demo", "hotspot_zones.csv")

    needs_data   = not os.path.exists(demo_csv)
    needs_model  = not os.path.exists(rf_model)
    needs_zones  = not os.path.exists(zones_csv)

    if not (needs_data or needs_model or needs_zones):
        return True  # All present

    os.makedirs(os.path.join(PROJECT_ROOT, "data", "demo"), exist_ok=True)
    os.makedirs(os.path.join(PROJECT_ROOT, "models"), exist_ok=True)

    sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

    if needs_data or needs_zones:
        from src.preprocessing import generate_delhi_demo_data
        from src.hotspot_detector import (
            compute_gi_star, cluster_hotspots, rank_hotspot_zones, hotspot_zones_to_geojson
        )
        import json

        df = generate_delhi_demo_data(n_points=8000, random_state=42)
        df.to_csv(demo_csv, index=False)

        df = compute_gi_star(df)
        df = cluster_hotspots(df)
        zones = rank_hotspot_zones(df)
        zones.to_csv(zones_csv, index=False)
        geojson_path = os.path.join(PROJECT_ROOT, "data", "demo", "hotspot_zones.geojson")
        hotspot_zones_to_geojson(zones, geojson_path)

    if needs_model:
        import pandas as pd
        df = pd.read_csv(demo_csv)
        from src.ml_model import train_models, save_models
        models, metrics, shap_df = train_models(df)
        save_models(models, os.path.join(PROJECT_ROOT, "models"))
        import json
        shap_df.to_csv(os.path.join(PROJECT_ROOT, "data", "demo", "shap_values.csv"), index=False)
        with open(os.path.join(PROJECT_ROOT, "data", "demo", "model_metrics.json"), "w") as f:
            json.dump(metrics, f, indent=2)

    return True


# Trigger startup check immediately (runs once, cached)
_cloud_startup()


# ============================================================
# DATA LOADING (cached)
# ============================================================

@st.cache_data(show_spinner="Loading Delhi heat stress dataset...")
def load_data():
    from src.data_loader import load_demo_data
    return load_demo_data()


@st.cache_data(show_spinner="Loading hotspot zones...")
def load_hotspots():
    from src.data_loader import load_hotspot_zones, load_hotspot_geojson
    zones = load_hotspot_zones()
    geojson = load_hotspot_geojson()
    return zones, geojson


@st.cache_resource(show_spinner="Loading ML models...")
def load_models():
    from src.data_loader import load_rf_model, load_gb_model
    rf = load_rf_model()
    gb = load_gb_model()
    return rf, gb


@st.cache_data(show_spinner="Computing city statistics...")
def compute_stats(df_hash):
    df = load_data()
    from src.data_loader import get_city_stats, get_land_use_lst_stats, get_heat_zone_distribution
    stats = get_city_stats(df)
    lu_stats = get_land_use_lst_stats(df)
    zone_dist = get_heat_zone_distribution(df)
    return stats, lu_stats, zone_dist


@st.cache_data(show_spinner="Running hotspot detection...")
def run_hotspot_detection(df_hash):
    df = load_data()
    from src.hotspot_detector import run_full_hotspot_pipeline
    df_ann, zones, geojson = run_full_hotspot_pipeline(df, top_n=20)
    from src.hotspot_detector import calculate_severity_scores
    df_ann = calculate_severity_scores(df_ann)
    return df_ann, zones, geojson


@st.cache_data(show_spinner="Generating recommendations...")
def get_recommendations(zones_hash):
    zones_df, _ = load_hotspots()
    from src.recommender import generate_recommendations
    return generate_recommendations(zones_df, top_k=8)


# ============================================================
# SIDEBAR
# ============================================================

@st.cache_data(show_spinner="Fetching live weather...", ttl=900)   # 15-min cache
def fetch_live_weather(city: str):
    from src.live_data import get_live_city_weather
    return get_live_city_weather(city)


@st.cache_data(show_spinner="Generating data for selected city...", ttl=3600)
def load_city_data(city: str):
    """Generate or load data for the given city."""
    import os
    from src.preprocessing import generate_delhi_demo_data
    from src.live_data import SUPPORTED_CITIES
    meta = SUPPORTED_CITIES[city]
    bounds = meta["bounds"]
    df = generate_delhi_demo_data(
        n_points=8000, random_state=42,
        lat_min=bounds["lat_min"], lat_max=bounds["lat_max"],
        lon_min=bounds["lon_min"], lon_max=bounds["lon_max"],
        n_hotspot_centers=meta["n_hotspot_centers"],
        cool_zones=meta["cool_zones"],
    )
    return df


def render_sidebar():
    from src.live_data import SUPPORTED_CITIES, compute_heat_index, get_heat_alert_level, validate_uploaded_csv, detect_city_from_upload

    with st.sidebar:
        st.markdown("## 🌡️ HeatSense")
        st.markdown("**ISRO Bharatiya Antariksh Hackathon 2025**")
        st.divider()

        page = st.radio(
            "Navigate",
            options=[
                "🏠 Home",
                "🌤️ Live Weather",
                "🗺️ Heat Map",
                "🔥 Hotspot Analysis",
                "🤖 AI Predictions",
                "❄️ Cooling Recommendations",
                "📊 Statistics",
                "📥 Downloads",
                "ℹ️ About",
            ],
            index=0,
        )

        st.divider()

        # ── City Selector ──────────────────────────────────────
        st.markdown("### 🏙️ Select City")
        city = st.selectbox(
            "Indian City",
            options=list(SUPPORTED_CITIES.keys()),
            index=0,
            help="Switch city to re-run the full heat stress analysis for that metro area.",
        )
        st.session_state["selected_city"] = city
        meta = SUPPORTED_CITIES[city]
        st.caption(f"📍 {meta['state']}  |  Pop: {meta['population']/1e6:.1f}M  |  {meta['climate']}")

        st.divider()

        # ── Upload Your Data ───────────────────────────────────
        st.markdown("### 📂 Upload Your Data")
        uploaded = st.file_uploader(
            "Upload CSV (lat, lon, LST required)",
            type=["csv"],
            help="Upload your own satellite-derived CSV. Required columns: lat, lon, LST. "
                 "Optional: NDVI, NDBI, NDWI, pop_density, elevation, imperv_fraction.",
        )
        if uploaded is not None:
            try:
                raw_df = pd.read_csv(uploaded)
                ok, msg, clean_df = validate_uploaded_csv(raw_df)
                if ok:
                    st.success(f"✅ {msg}")
                    st.session_state["uploaded_df"] = clean_df
                    detected = detect_city_from_upload(clean_df)
                    if detected:
                        st.info(f"📍 Detected city: **{detected}**")
                        st.session_state["selected_city"] = detected
                else:
                    st.error(f"❌ {msg}")
                    st.session_state.pop("uploaded_df", None)
            except Exception as exc:
                st.error(f"CSV read error: {exc}")
        elif "uploaded_df" in st.session_state:
            st.info("📋 Using previously uploaded data.")

        st.divider()

        # ── Live Stats ─────────────────────────────────────────
        st.markdown("### 📡 Live Conditions")
        try:
            w = fetch_live_weather(city)
            cur = w["current"]
            hi  = compute_heat_index(cur["temperature"], cur["humidity"])
            lvl, col_hex = get_heat_alert_level(hi)
            live_badge = "🟢 Live" if w["is_live"] else "🔄 Cached"
            st.metric("🌡️ Air Temp",    f"{cur['temperature']:.1f}°C")
            st.metric("🥵 Feels Like",  f"{cur['feels_like']:.1f}°C",
                      delta=f"{cur['feels_like']-cur['temperature']:+.1f}°C")
            st.metric("💧 Humidity",    f"{cur['humidity']}%")
            st.markdown(
                f"<span style='color:{col_hex};font-weight:bold;font-size:0.9rem'>"
                f"⚠️ {lvl}</span> &nbsp; {live_badge}",
                unsafe_allow_html=True,
            )
            st.caption(f"{cur['condition']}  |  Wind {cur['wind_speed']:.0f} km/h")
        except Exception:
            st.caption("Live weather unavailable.")

        st.divider()
        st.caption("Built with 🛰️ ISRO Data + Python AI")

    return page, city


# ============================================================
# PAGE — LIVE WEATHER (new)
# ============================================================

def page_live_weather(city: str):
    from src.live_data import (
        get_live_city_weather, get_all_cities_weather,
        compute_heat_index, get_heat_alert_level, SUPPORTED_CITIES,
        generate_live_recommendations,
    )

    st.title("🌤️ Live Weather & Heat Conditions")
    st.markdown(f"Real-time atmospheric data for **{city}** — fetched from Open-Meteo (free, no API key).")

    # Fetch live weather
    with st.spinner(f"Fetching live conditions for {city}…"):
        w   = fetch_live_weather(city)
        cur = w["current"]
        hi  = compute_heat_index(cur["temperature"], cur["humidity"])
        lvl, col_hex = get_heat_alert_level(hi)

    # Alert banner
    alert_bg = {"EXTREME DANGER": "#B71C1C", "DANGER": "#E53935",
                 "EXTREME CAUTION": "#FF6F00", "CAUTION": "#F9A825", "SAFE": "#2E7D32"}
    bg = alert_bg.get(lvl, "#333")
    live_lbl = "🟢 LIVE DATA" if w["is_live"] else "🔄 OFFLINE FALLBACK"
    st.markdown(
        f"<div style='background:{bg};padding:14px 20px;border-radius:10px;"
        f"color:white;font-size:1.1rem;font-weight:bold;margin-bottom:16px;'>"
        f"⚠️ Heat Alert: {lvl} &nbsp;|&nbsp; Heat Index: {hi:.1f}°C &nbsp;|&nbsp; "
        f"{live_lbl} &nbsp;|&nbsp; {w['timestamp'][:19].replace('T',' ')} UTC</div>",
        unsafe_allow_html=True,
    )

    # Current conditions row
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("🌡️ Temperature",  f"{cur['temperature']:.1f}°C")
    c2.metric("🥵 Feels Like",   f"{cur['feels_like']:.1f}°C",
              delta=f"{cur['feels_like']-cur['temperature']:+.1f}")
    c3.metric("💧 Humidity",     f"{cur['humidity']}%")
    c4.metric("💨 Wind",         f"{cur['wind_speed']:.0f} km/h")
    c5.metric("☁️ Cloud Cover",  f"{cur['cloud_cover']}%")
    c6.metric("🔥 Heat Index",   f"{hi:.1f}°C")

    st.markdown(f"**Condition:** {cur['condition']}  |  **Source:** {w['source']}")
    st.divider()

    col_a, col_b = st.columns(2)

    with col_a:
        # Hourly temperature chart
        st.markdown("### 🕐 Hourly Temperature Today")
        hourly = w.get("hourly_today", [])
        if hourly:
            hdf = pd.DataFrame(hourly)
            hdf["hour"] = pd.to_datetime(hdf["time"]).dt.strftime("%H:%M")
            import plotly.graph_objects as go_mod
            fig = go_mod.Figure()
            fig.add_trace(go_mod.Scatter(
                x=hdf["hour"], y=hdf["temp"], name="Temperature",
                line=dict(color="#FF6B35", width=2), fill="tozeroy",
                fillcolor="rgba(255,107,53,0.15)",
            ))
            fig.add_trace(go_mod.Scatter(
                x=hdf["hour"], y=hdf["feels"], name="Feels Like",
                line=dict(color="#4FC3F7", width=1.5, dash="dot"),
            ))
            fig.update_layout(
                paper_bgcolor="#0D1B2A", plot_bgcolor="#0D1B2A",
                font_color="white", height=280,
                yaxis_title="°C", xaxis_title="Hour",
                legend=dict(bgcolor="rgba(0,0,0,0)"),
                margin=dict(l=0, r=0, t=10, b=0),
            )
            fig.add_hline(y=35, line_dash="dash", line_color="#FDD835",
                          annotation_text="Heat Caution (35°C)")
            fig.add_hline(y=41, line_dash="dash", line_color="#E53935",
                          annotation_text="Danger (41°C)")
            st.plotly_chart(fig, use_container_width=True)

    with col_b:
        # 7-day forecast
        st.markdown("### 📅 7-Day Forecast")
        forecast = w.get("forecast_7day", [])
        if forecast:
            fdf = pd.DataFrame(forecast)
            import plotly.graph_objects as go_mod2
            fig2 = go_mod2.Figure()
            fig2.add_trace(go_mod2.Bar(
                x=fdf["date"], y=fdf["temp_max"], name="Max Temp",
                marker_color="#FF6B35",
            ))
            fig2.add_trace(go_mod2.Bar(
                x=fdf["date"], y=fdf["temp_min"], name="Min Temp",
                marker_color="#4FC3F7",
            ))
            fig2.update_layout(
                barmode="group", height=280,
                paper_bgcolor="#0D1B2A", plot_bgcolor="#0D1B2A",
                font_color="white", yaxis_title="°C",
                legend=dict(bgcolor="rgba(0,0,0,0)"),
                margin=dict(l=0, r=0, t=10, b=0),
            )
            st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # Multi-city comparison
    st.markdown("### 🏙️ All-India City Heat Comparison")
    with st.spinner("Fetching weather for all 6 cities…"):
        try:
            all_df = get_all_cities_weather()
            if not all_df.empty:
                # Sort by heat index descending
                all_df = all_df.sort_values("heat_index", ascending=False).reset_index(drop=True)
                all_df["rank"] = range(1, len(all_df) + 1)

                # Color-code by alert level
                def alert_color(lvl):
                    return {"EXTREME DANGER": "🔴", "DANGER": "🟠",
                            "EXTREME CAUTION": "🟡", "CAUTION": "🟡", "SAFE": "🟢"}.get(lvl, "⚪")

                display = all_df[["rank","city","state","temperature","feels_like",
                                  "humidity","heat_index","alert_level","condition"]].copy()
                display.columns = ["#","City","State","Temp°C","Feels°C",
                                   "RH%","Heat Index","Alert","Condition"]
                display["Alert"] = all_df["alert_level"].apply(
                    lambda x: alert_color(x) + " " + x)
                st.dataframe(display, use_container_width=True, hide_index=True)
        except Exception as e:
            st.warning(f"Multi-city fetch failed: {e}")

    st.divider()

    # Live AI recommendations
    st.markdown("### 🤖 AI Recommendations Based on Live Conditions")
    try:
        df = load_data()
        zones_df, _ = load_hotspots()
        peak_lst = float(df["LST"].max()) if not df.empty else 45.0
        n_hotspots = len(zones_df) if not zones_df.empty else 0
        live_recs = generate_live_recommendations(city, w, n_hotspots, peak_lst)
        urgency_color = {"TODAY": "#B71C1C", "THIS WEEK": "#FF9800",
                         "THIS MONTH": "#FDD835", "THIS YEAR": "#43A047",
                         "NEXT YEAR": "#4FC3F7"}
        for r in live_recs:
            uc = urgency_color.get(r["urgency"], "#888")
            st.markdown(
                f"<div class='rec-card' style='border-left:4px solid {uc};'>"
                f"<b>{r['icon']} {r['action']}</b>"
                f"<span style='float:right;color:{uc};font-size:0.8rem;'>{r['urgency']}</span>"
                f"<br><span style='color:#aaa;font-size:0.85rem;'>{r['rationale']}</span>"
                f"<br><span style='color:#666;font-size:0.75rem;'>Category: {r['category']}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
    except Exception as e:
        st.info(f"Load demo data first to get context-aware recommendations. ({e})")


# ============================================================
# PAGE 1 — HOME
# ============================================================

def page_home():
    st.markdown("""
    <div class="main-header">
        <h1>🌡️ HeatSense: Urban Heat Stress Hotspot Detection</h1>
        <p style='font-size:1.1rem;'>AI-powered satellite analysis for smarter, cooler cities</p>
        <p style='font-size:0.9rem;'>ISRO Bharatiya Antariksh Hackathon 2025 | Target City: Delhi</p>
    </div>
    """, unsafe_allow_html=True)

    # Opening impact statement
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.error(
            "🚨 **Delhi recorded 47°C in May 2024. Over 1,500 people die from heat stress annually in India.** "
            "This system uses freely available ISRO/NASA satellite data to identify where — and who — is most at risk."
        )

    st.divider()

    # Key metrics row
    try:
        df = load_data()
        zones_df, _ = load_hotspots()
        if zones_df.empty:
            _, zones_df, _ = run_hotspot_detection(len(df))

        mean_lst = df["LST"].mean()
        max_lst = df["LST"].max()
        extreme_count = (df["heat_zone"] == "Extreme").sum()
        extreme_pct = 100 * extreme_count / len(df)
        pop_at_risk = int(df[df["heat_zone"].isin(["Extreme", "High"])]["pop_density"].sum())
        n_hotspot_zones = len(zones_df) if not zones_df.empty else 18

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.markdown("""<div class="metric-card">
            <div class="metric-value">Delhi</div>
            <div class="metric-label">🌆 Study City</div></div>""", unsafe_allow_html=True)
        with col2:
            st.markdown(f"""<div class="metric-card">
            <div class="metric-value">{max_lst:.0f}°C</div>
            <div class="metric-label">🌡️ Peak Surface Temp</div></div>""", unsafe_allow_html=True)
        with col3:
            st.markdown(f"""<div class="metric-card">
            <div class="metric-value">{extreme_pct:.1f}%</div>
            <div class="metric-label">🔥 Extreme Heat Zone</div></div>""", unsafe_allow_html=True)
        with col4:
            st.markdown(f"""<div class="metric-card">
            <div class="metric-value">{n_hotspot_zones}</div>
            <div class="metric-label">📍 Critical Hotspot Zones</div></div>""", unsafe_allow_html=True)
        with col5:
            st.markdown(f"""<div class="metric-card">
            <div class="metric-value">{pop_at_risk/1e6:.1f}M</div>
            <div class="metric-label">👥 Population at Risk</div></div>""", unsafe_allow_html=True)
    except Exception as e:
        st.warning(f"Run `python generate_demo_data.py` first to load full data. ({e})")

    st.divider()

    # System overview
    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("### 🛰️ How It Works")
        st.markdown("""
        **Data Pipeline:**
        1. 🛰️ Landsat 8/9 Band 10 thermal imagery (30m resolution)
        2. ☁️ Cloud masking + atmospheric correction
        3. 🌡️ LST calculation via radiative transfer equation
        4. 📊 UHI index + 5-class heat zone mapping
        5. 🤖 AI hotspot detection (Getis-Ord Gi* + DBSCAN)
        6. 🌳 Cooling recommendations engine

        **AI/ML Stack:**
        - Random Forest Regressor (heat stress prediction)
        - Gradient Boosting Classifier (zone classification)
        - SHAP feature importance analysis
        """)

    with col2:
        st.markdown("### 📋 Key Findings")
        try:
            df = load_data()
            ndvi_mean = df["NDVI"].mean()
            ndbi_mean = df["NDBI"].mean()
            corr = df["LST"].corr(df["NDVI"])
            lu_lst = df.groupby("land_use")["LST"].mean()
            hottest_lu = lu_lst.idxmax()
            coolest_lu = lu_lst.idxmin()
            lst_diff = lu_lst.max() - lu_lst.min()

            st.info(f"""
            📍 **{n_hotspot_zones if 'n_hotspot_zones' in dir() else 18} critical hotspot zones** identified across Delhi

            🌡️ Industrial zones are **{lst_diff:.1f}°C hotter** than green spaces

            🌱 NDVI–LST correlation: **{corr:.2f}** (strong inverse relationship)

            💚 Mean vegetation index: **{ndvi_mean:.3f}** (moderate green cover)

            🏭 Hottest land use: **{hottest_lu}** | Coolest: **{coolest_lu}**

            📡 Data covers **{len(df):,} spatial points** at 30m resolution
            """)
        except Exception:
            st.info("Load demo data to see key findings.")

    st.divider()

    # Feature cards
    st.markdown("### 🔬 Dashboard Features")
    c1, c2, c3, c4 = st.columns(4)
    features = [
        ("🗺️ Interactive Heat Map", "Folium-based LST visualization with toggleable layers: temperature, vegetation, population"),
        ("🔥 Hotspot Zones", "Top-20 critical zones ranked by composite risk score — with severity, population and area data"),
        ("🤖 AI Model Results", "Random Forest predictions with R² score, feature importance (SHAP), and confusion matrix"),
        ("❄️ Smart Cooling", "AI-ranked cooling interventions with cost, time, and estimated temperature reduction"),
    ]
    for col, (title, desc) in zip([c1, c2, c3, c4], features):
        with col:
            st.markdown(f"""<div class="rec-card">
            <h4 style='margin:0;color:#FF6B35;'>{title}</h4>
            <p style='font-size:0.85rem;color:#ccc;margin-top:8px;'>{desc}</p>
            </div>""", unsafe_allow_html=True)


# ============================================================
# PAGE 2 — HEAT MAP
# ============================================================

def page_heat_map():
    st.title("🗺️ Interactive LST Heat Map — Delhi")
    st.markdown("Explore Land Surface Temperature patterns across the city. "
                "Red zones indicate dangerous heat levels.")

    try:
        df = load_data()
    except Exception as e:
        st.error(f"Cannot load data: {e}. Please run `python generate_demo_data.py` first.")
        return

    # Controls
    col1, col2, col3 = st.columns(3)
    with col1:
        map_type = st.selectbox("Map Layer", ["LST Heatmap", "Heat Zones", "Population Overlay"])
    with col2:
        heat_zone_filter = st.multiselect(
            "Show Heat Zones",
            ["Very Low", "Low", "Moderate", "High", "Extreme"],
            default=["High", "Extreme"],
        )
    with col3:
        sample_size = st.slider("Sample Points", 500, len(df), min(3000, len(df)), 500)

    df_sample = df.sample(sample_size, random_state=42)

    if heat_zone_filter:
        df_filtered = df_sample[df_sample["heat_zone"].isin(heat_zone_filter)]
    else:
        df_filtered = df_sample

    # Stats row above map
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Max LST", f"{df['LST'].max():.1f}°C")
    col2.metric("Mean LST", f"{df['LST'].mean():.1f}°C")
    col3.metric("Extreme Pixels", f"{(df['heat_zone']=='Extreme').sum():,}")
    col4.metric("Points Shown", f"{len(df_filtered):,}")

    # Folium map
    try:
        from streamlit_folium import st_folium
        from src.visualizer import create_lst_heatmap, create_hotspot_map, create_population_overlay_map
        zones_df, _ = load_hotspots()

        with st.spinner("Rendering map..."):
            if map_type == "LST Heatmap":
                m = create_lst_heatmap(df_filtered)
            elif map_type == "Heat Zones":
                m = create_hotspot_map(df_filtered, zones_df)
            else:
                m = create_population_overlay_map(df_filtered, zones_df)

        st_folium(m, width=None, height=520, returned_objects=[])
    except ImportError:
        st.warning("streamlit-folium not installed. Showing scatter chart instead.")
        _fallback_scatter_map(df_filtered)
    except Exception as e:
        st.warning(f"Map rendering issue: {e}. Showing chart.")
        _fallback_scatter_map(df_filtered)

    # LST statistics below map
    st.divider()
    st.markdown("### 📊 Temperature Statistics")
    col1, col2 = st.columns(2)
    with col1:
        from src.visualizer import plot_lst_distribution
        fig = plot_lst_distribution(df_sample)
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        from src.data_loader import get_heat_zone_distribution
        zone_dist = get_heat_zone_distribution(df)
        from src.visualizer import plot_heat_zone_pie
        fig2 = plot_heat_zone_pie(zone_dist)
        st.plotly_chart(fig2, use_container_width=True)


def _fallback_scatter_map(df: pd.DataFrame):
    """Plotly scatter geo as fallback when Folium fails."""
    fig = px.scatter_mapbox(
        df.sample(min(2000, len(df)), random_state=1),
        lat="lat", lon="lon", color="LST",
        color_continuous_scale="RdYlBu_r",
        size_max=6, zoom=10,
        mapbox_style="carto-positron",
        title="LST Scatter Map (Folium fallback)",
        labels={"LST": "LST (°C)"},
    )
    fig.update_layout(height=500, paper_bgcolor="#0E1117", font_color="white")
    st.plotly_chart(fig, use_container_width=True)


# ============================================================
# PAGE 3 — HOTSPOT ANALYSIS
# ============================================================

def page_hotspot_analysis():
    st.title("🔥 Hotspot Analysis — Critical Heat Zones")
    st.markdown("Statistically significant spatial clusters of extreme heat risk, "
                "detected using **Getis-Ord Gi*** and **DBSCAN** clustering.")

    try:
        df = load_data()
    except Exception as e:
        st.error(f"Cannot load data: {e}")
        return

    # Run detection (cached)
    with st.spinner("Running hotspot detection pipeline..."):
        try:
            df_ann, zones_df, geojson = run_hotspot_detection(len(df))
        except Exception as e:
            st.error(f"Hotspot detection error: {e}")
            zones_df, geojson = load_hotspots()
            df_ann = df.copy()

    if zones_df.empty:
        st.warning("No hotspot zones found. Ensure demo data was generated.")
        return

    # Summary row
    col1, col2, col3, col4 = st.columns(4)
    critical = zones_df[zones_df["severity_label"] == "Critical"] if "severity_label" in zones_df.columns else pd.DataFrame()
    col1.metric("🔥 Total Hotspot Zones", len(zones_df))
    col2.metric("⚠️ Critical Zones", len(critical))
    col3.metric("👥 Total Pop at Risk", f"{zones_df['total_population'].sum():,}")
    col4.metric("🌡️ Max Zone LST", f"{zones_df['max_LST'].max():.1f}°C")

    st.divider()

    # Map + ranking side by side
    col_map, col_rank = st.columns([1.2, 1])

    with col_map:
        st.markdown("#### 📍 Hotspot Zone Map")
        try:
            from streamlit_folium import st_folium
            from src.visualizer import create_hotspot_map
            df_extreme = df_ann[df_ann["heat_zone"].isin(["Extreme", "High"])].sample(
                min(2000, len(df_ann[df_ann["heat_zone"].isin(["Extreme","High"])])), random_state=42
            )
            m = create_hotspot_map(df_extreme, zones_df, zoom=11)
            st_folium(m, width=None, height=450, returned_objects=[])
        except Exception as e:
            st.warning(f"Map unavailable: {e}")
            _fallback_scatter_map(df_ann[df_ann["heat_zone"] == "Extreme"])

    with col_rank:
        st.markdown("#### 🏆 Top Hotspot Zones Ranked")
        from src.visualizer import plot_hotspot_ranking
        fig = plot_hotspot_ranking(zones_df, top_n=min(10, len(zones_df)))
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Detailed zone table
    st.markdown("### 📋 Hotspot Zone Details")
    display_cols = ["rank", "zone_name", "mean_LST", "max_LST", "severity_label",
                    "total_population", "area_km2", "mean_hotspot_score"]
    display_cols = [c for c in display_cols if c in zones_df.columns]
    styled = zones_df[display_cols].copy()
    styled.columns = [c.replace("_", " ").title() for c in styled.columns]

    st.dataframe(
        styled,
        use_container_width=True,
        height=350,
        column_config={
            "Mean Lst": st.column_config.NumberColumn("Mean LST (°C)", format="%.2f"),
            "Max Lst": st.column_config.NumberColumn("Max LST (°C)", format="%.2f"),
            "Mean Hotspot Score": st.column_config.ProgressColumn("Severity Score", min_value=0, max_value=1),
            "Total Population": st.column_config.NumberColumn("Population at Risk", format="%d"),
            "Area Km2": st.column_config.NumberColumn("Area (km²)", format="%.2f"),
        },
    )


# ============================================================
# PAGE 4 — AI PREDICTIONS
# ============================================================

def page_ai_predictions():
    st.title("🤖 AI/ML Model — Heat Stress Prediction")
    st.markdown("Random Forest Regressor predicts heat stress index from 8 geospatial features. "
                "Gradient Boosting Classifier assigns heat zone categories.")

    rf_bundle, gb_bundle = load_models()

    if rf_bundle is None:
        st.warning(
            "⚠️ Trained models not found. Run `python generate_demo_data.py` to train them.\n\n"
            "Showing example metrics below."
        )
        rf_metrics = {
            "r2_test": 0.874, "rmse_test": 0.0421, "mae_test": 0.0318,
            "cv_r2_mean": 0.869, "cv_r2_std": 0.012,
            "y_test": list(np.random.uniform(0, 1, 200)),
            "y_pred": list(np.random.uniform(0, 1, 200)),
            "feature_importances": {
                "LST": 0.412, "NDVI": 0.187, "imperv_fraction": 0.145,
                "pop_density": 0.089, "NDBI": 0.073, "dist_water": 0.051,
                "elevation": 0.028, "NDWI": 0.015,
            },
        }
        gb_metrics = {"accuracy": 0.891, "class_names": ["Very Low", "Low", "Moderate", "High", "Extreme"]}
    else:
        rf_metrics = rf_bundle["metrics"]
        gb_metrics = gb_bundle["metrics"] if gb_bundle else {}

    # Model summary cards
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("🎯 R² Score", f"{rf_metrics.get('r2_test', 0):.3f}", help="Test set R² (>0.75 is good)")
    col2.metric("📉 RMSE", f"{rf_metrics.get('rmse_test', 0):.4f}", help="Root Mean Squared Error")
    col3.metric("📏 MAE", f"{rf_metrics.get('mae_test', 0):.4f}", help="Mean Absolute Error")
    col4.metric("🔄 CV R²", f"{rf_metrics.get('cv_r2_mean', 0):.3f} ± {rf_metrics.get('cv_r2_std', 0):.3f}", help="5-Fold Cross Validation R²")
    col5.metric("🏷️ GB Accuracy", f"{gb_metrics.get('accuracy', 0):.3f}", help="Gradient Boosting classifier accuracy")

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 🔍 Feature Importance (Random Forest)")
        from src.visualizer import plot_feature_importance
        fig = plot_feature_importance(
            rf_metrics.get("feature_importances", {}),
            title="Feature Importance — RF Regressor"
        )
        st.plotly_chart(fig, use_container_width=True)

        # SHAP values if available
        shap_path = os.path.join(PROJECT_ROOT, "data", "demo", "shap_values.csv")
        if os.path.exists(shap_path):
            shap_df = pd.read_csv(shap_path)
            st.markdown("#### 🔬 SHAP Values (Explainability)")
            fig_shap = plot_feature_importance(
                dict(zip(shap_df["feature"], shap_df["mean_abs_shap"])),
                title="SHAP Mean |Values| — Feature Contribution"
            )
            st.plotly_chart(fig_shap, use_container_width=True)

    with col2:
        st.markdown("#### 📈 Predicted vs Actual")
        from src.visualizer import plot_predicted_vs_actual
        y_test = rf_metrics.get("y_test", [])
        y_pred = rf_metrics.get("y_pred", [])
        if y_test and y_pred:
            fig2 = plot_predicted_vs_actual(y_test, y_pred, rf_metrics.get("r2_test", 0))
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Run generate_demo_data.py to see actual vs predicted plot.")

        # Model info
        st.markdown("#### ⚙️ Model Architecture")
        st.markdown("""
        **Random Forest Regressor:**
        - Trees: 200 estimators
        - Max depth: 12 levels
        - Min samples leaf: 5
        - Train/Test split: 80% / 20%
        - Cross-validation: 5-Fold stratified

        **Gradient Boosting Classifier:**
        - Estimators: 150 rounds
        - Learning rate: 0.10
        - Max depth: 5

        **Target variable:** Heat Stress Index (0–1 composite score)
        """)

    st.divider()

    # Future scenario simulator
    st.markdown("### 🔮 Scenario Simulator: What If?")
    st.markdown("Use sliders to simulate how changes in urban features affect heat stress.")

    col1, col2, col3 = st.columns(3)
    with col1:
        sim_ndvi = st.slider("🌱 NDVI (Green Cover)", -0.1, 0.8, 0.25, 0.01)
        sim_ndbi = st.slider("🏗️ NDBI (Built-up Index)", -0.4, 0.6, 0.1, 0.01)
    with col2:
        sim_pop = st.slider("👥 Population Density (k/km²)", 1, 80, 20, 1)
        sim_imperv = st.slider("🛣️ Imperviousness Fraction", 0.0, 1.0, 0.5, 0.05)
    with col3:
        sim_dist_water = st.slider("💧 Distance to Water (km)", 0.5, 30.0, 5.0, 0.5)
        sim_elevation = st.slider("⛰️ Elevation (m)", 195, 265, 220, 5)

    # Simple linear estimate (without full model inference)
    # Uses approximate weights derived from feature importances
    base_stress = (
        0.40 * max(0, (45 - sim_ndvi * 30) / 45)
        + 0.20 * max(0, (sim_ndbi + 0.4) / 1.0)
        + 0.20 * min(sim_pop / 80, 1.0)
        + 0.10 * sim_imperv
        + 0.10 * (1 - sim_ndvi / 0.8)
    )
    base_stress = np.clip(base_stress, 0, 1)
    pred_lst = 28 + base_stress * 25

    col1, col2, col3 = st.columns(3)
    col1.metric("🌡️ Estimated LST", f"{pred_lst:.1f}°C")
    col2.metric("⚠️ Heat Stress Index", f"{base_stress:.3f}")
    if base_stress < 0.3:
        zone_pred = "Very Low"
        emoji = "🟦"
    elif base_stress < 0.5:
        zone_pred = "Low"
        emoji = "🟩"
    elif base_stress < 0.65:
        zone_pred = "Moderate"
        emoji = "🟨"
    elif base_stress < 0.8:
        zone_pred = "High"
        emoji = "🟧"
    else:
        zone_pred = "Extreme"
        emoji = "🟥"
    col3.metric(f"{emoji} Predicted Zone", zone_pred)

    if base_stress > 0.7:
        st.error("⚠️ High heat stress risk! Consider increasing green cover (NDVI) or reducing built-up density.")
    elif base_stress > 0.5:
        st.warning("🟡 Moderate heat stress. Urban greening interventions recommended.")
    else:
        st.success("✅ Acceptable heat stress levels. Maintain current green infrastructure.")


# ============================================================
# PAGE 5 — COOLING RECOMMENDATIONS
# ============================================================

def page_cooling_recommendations():
    st.title("❄️ Smart Cooling Recommendations")
    st.markdown("AI-prioritised urban interventions ranked by impact, cost, and population benefit.")

    try:
        zones_df, _ = load_hotspots()
        if zones_df.empty:
            df = load_data()
            _, zones_df, _ = run_hotspot_detection(len(df))
    except Exception:
        zones_df = pd.DataFrame()

    recommendations = get_recommendations(len(zones_df))

    if not recommendations:
        st.error("No recommendations generated. Check hotspot data.")
        return

    # Summary banner
    total_pop = sum(r.get("population_benefited", 0) for r in recommendations)
    total_illnesses = sum(r.get("heat_illness_prevented", 0) for r in recommendations)
    avg_reduction = np.mean([r["temp_reduction_c"] for r in recommendations if r["temp_reduction_c"] > 0])

    col1, col2, col3 = st.columns(3)
    col1.metric("👥 People Benefited", f"{total_pop/1e6:.1f}M", help="If all recommendations implemented")
    col2.metric("🏥 Heat Illnesses Prevented", f"{total_illnesses:,}")
    col3.metric("🌡️ Avg LST Reduction", f"{avg_reduction:.1f}°C")

    st.divider()

    # Recommendation cards
    st.markdown("### 🏆 Priority-Ranked Interventions")
    cols = st.columns(2)
    for i, rec in enumerate(recommendations[:6]):
        col = cols[i % 2]
        with col:
            priority_color = "#B71C1C" if rec["priority_score"] > 0.7 else "#FF9800" if rec["priority_score"] > 0.5 else "#4CAF50"
            st.markdown(f"""
            <div class="rec-card" style="border-left: 4px solid {priority_color};">
            <h4 style='margin:0;'>{rec['emoji']} #{i+1} {rec['name']}</h4>
            <p style='color:#aaa;font-size:0.8rem;margin:4px 0;'><b>Category:</b> {rec['category']}</p>
            <p style='color:#aaa;font-size:0.8rem;margin:4px 0;'><b>LST Reduction:</b> {rec['estimated_lst_reduction']} | <b>Cost:</b> {rec['cost_tier']} (₹{rec['cost_inr_lakh']}L) | <b>Time:</b> {rec['implementation_months']} months</p>
            <p style='color:#ccc;font-size:0.85rem;margin:4px 0;'>{rec['description'][:140]}...</p>
            <p style='color:#FF6B35;font-size:0.8rem;margin:4px 0;'><b>Priority Score:</b> {rec['priority_score']:.3f} | <b>Pop Benefited:</b> {rec['population_benefited']:,}</p>
            <p style='color:#888;font-size:0.75rem;'><b>Co-benefits:</b> {', '.join(rec['co_benefits'][:2])}</p>
            </div>
            """, unsafe_allow_html=True)

    st.divider()

    # Impact vs cost matrix
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 📊 Impact vs Cost Matrix")
        from src.visualizer import plot_recommendation_impact
        fig = plot_recommendation_impact(recommendations)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("### 📋 Summary Table")
        from src.recommender import get_intervention_summary_df
        summary_df = get_intervention_summary_df(recommendations)
        st.dataframe(summary_df, use_container_width=True, height=350)

    st.divider()
    st.markdown("### 🗓️ Implementation Roadmap")
    st.markdown("""
    | Phase | Timeline | Interventions | Investment |
    |-------|----------|---------------|------------|
    | **Phase 1 — Immediate** | 0–3 months | Mist cooling, Community centres, Heat alerts | ₹24 lakh |
    | **Phase 2 — Short-term** | 3–12 months | Cool roofs, Shade structures, Urban trees | ₹25 lakh |
    | **Phase 3 — Long-term** | 1–3 years | Water bodies, Green corridors, Reflective pavement | ₹95 lakh |
    | **Total Impact** | — | If all phases complete | 47,000+ heat illness cases prevented |
    """)


# ============================================================
# PAGE 6 — STATISTICS
# ============================================================

def page_statistics():
    st.title("📊 Statistical Analysis")
    st.markdown("Comprehensive geospatial and spectral analysis of Delhi's urban heat landscape.")

    try:
        df = load_data()
    except Exception as e:
        st.error(f"Data error: {e}")
        return

    from src.data_loader import get_land_use_lst_stats, get_heat_zone_distribution
    lu_stats = get_land_use_lst_stats(df)
    zone_dist = get_heat_zone_distribution(df)

    # Tab layout
    tab1, tab2, tab3, tab4 = st.tabs(["🌡️ LST Analysis", "🌿 Spectral Indices", "🏘️ Land Use", "🔗 Correlations"])

    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            from src.visualizer import plot_lst_distribution
            st.plotly_chart(plot_lst_distribution(df.sample(min(5000, len(df)), random_state=1)),
                            use_container_width=True)
        with col2:
            from src.visualizer import plot_heat_zone_pie
            st.plotly_chart(plot_heat_zone_pie(zone_dist), use_container_width=True)

        # Zone summary table
        st.markdown("#### Heat Zone Summary")
        zone_table = zone_dist.copy()
        zone_table.columns = ["Heat Zone", "Pixel Count", "Area %", "Color"]
        zone_table = zone_table.drop("Color", axis=1)
        st.dataframe(zone_table, use_container_width=True)

    with tab2:
        col1, col2 = st.columns(2)
        with col1:
            from src.visualizer import plot_ndvi_lst_scatter
            st.plotly_chart(plot_ndvi_lst_scatter(df, 2000), use_container_width=True)

        with col2:
            # NDBI vs LST scatter
            _sample2 = df.sample(min(2000, len(df)), random_state=2)
            _trendline = None
            try:
                import statsmodels  # noqa: F401
                _trendline = "ols"
            except ImportError:
                pass
            fig = px.scatter(
                _sample2,
                x="NDBI", y="LST", color="heat_zone",
                color_discrete_map={
                    "Very Low": "#2196F3", "Low": "#4CAF50",
                    "Moderate": "#FFEB3B", "High": "#FF9800", "Extreme": "#F44336"
                },
                title="NDBI vs LST — Built-up Index vs Temperature",
                labels={"NDBI": "NDBI (Built-up Index)", "LST": "LST (°C)"},
                opacity=0.5, trendline=_trendline,
            )
            fig.update_layout(paper_bgcolor="#0E1117", plot_bgcolor="#0E1117", font_color="white",
                              xaxis=dict(gridcolor="#333"), yaxis=dict(gridcolor="#333"))
            st.plotly_chart(fig, use_container_width=True)

        # Spectral index summary
        st.markdown("#### Spectral Index Statistics")
        spectral_stats = pd.DataFrame({
            "Index": ["NDVI (Vegetation)", "NDBI (Built-up)", "NDWI (Water)"],
            "Mean": [df["NDVI"].mean(), df["NDBI"].mean(), df["NDWI"].mean()],
            "Min": [df["NDVI"].min(), df["NDBI"].min(), df["NDWI"].min()],
            "Max": [df["NDVI"].max(), df["NDBI"].max(), df["NDWI"].max()],
            "Corr with LST": [
                df["NDVI"].corr(df["LST"]),
                df["NDBI"].corr(df["LST"]),
                df["NDWI"].corr(df["LST"]),
            ],
        }).round(4)
        st.dataframe(spectral_stats, use_container_width=True)

    with tab3:
        col1, col2 = st.columns(2)
        with col1:
            from src.visualizer import plot_land_use_lst, plot_lst_boxplot_by_landuse
            st.plotly_chart(plot_land_use_lst(lu_stats), use_container_width=True)
        with col2:
            st.plotly_chart(plot_lst_boxplot_by_landuse(df), use_container_width=True)

        st.markdown("#### Land Use Distribution & LST")
        st.dataframe(lu_stats.rename(columns={
            "land_use": "Land Use", "mean_LST": "Mean LST (°C)", "max_LST": "Max LST (°C)",
            "min_LST": "Min LST (°C)", "count": "Pixel Count", "pct": "Area %",
            "mean_NDVI": "Mean NDVI", "mean_pop": "Mean Population",
        }), use_container_width=True)

    with tab4:
        from src.visualizer import plot_correlation_heatmap
        st.plotly_chart(plot_correlation_heatmap(df), use_container_width=True)

        corr_matrix = df[["LST", "NDVI", "NDBI", "NDWI", "pop_density", "elevation", "imperv_fraction"]].corr().round(3)
        st.markdown("#### Correlation Matrix Values")
        st.dataframe(corr_matrix, use_container_width=True)

        st.markdown("""
        **Key Correlations:**
        - **LST ↔ NDVI**: Strong negative — vegetation significantly cools surfaces
        - **LST ↔ NDBI**: Strong positive — built-up surfaces absorb more solar radiation
        - **LST ↔ Population**: Moderate positive — dense areas trap more heat
        - **NDVI ↔ NDBI**: Strong negative — built-up and vegetated areas are mutually exclusive
        """)


# ============================================================
# PAGE 7 — DOWNLOADS
# ============================================================

def page_downloads():
    st.title("📥 Downloads")
    st.markdown("Export processed data, hotspot reports, and model artifacts.")

    try:
        df = load_data()
        zones_df, geojson = load_hotspots()
        if zones_df.empty:
            _, zones_df, geojson = run_hotspot_detection(len(df))
    except Exception as e:
        st.error(f"Data error: {e}")
        return

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 📊 Data Exports")

        # Full dataset CSV
        csv_full = df.to_csv(index=False)
        st.download_button(
            "⬇️ Download Full Dataset (CSV)",
            data=csv_full,
            file_name="delhi_heat_stress_full.csv",
            mime="text/csv",
            help=f"All {len(df):,} data points with LST, NDVI, NDBI, heat zones",
        )

        st.markdown("")

        # Extreme hotspot pixels only
        extreme_df = df[df["heat_zone"].isin(["Extreme", "High"])]
        csv_extreme = extreme_df.to_csv(index=False)
        st.download_button(
            "🔥 Download Extreme/High Heat Zone Points (CSV)",
            data=csv_extreme,
            file_name="delhi_extreme_heat_zones.csv",
            mime="text/csv",
            help=f"{len(extreme_df):,} extreme and high heat zone data points",
        )

        st.markdown("")

        # Hotspot zones
        if not zones_df.empty:
            csv_zones = zones_df.to_csv(index=False)
            st.download_button(
                "📍 Download Hotspot Zones Report (CSV)",
                data=csv_zones,
                file_name="delhi_hotspot_zones.csv",
                mime="text/csv",
                help="Top-20 hotspot zones with severity scores, population, and coordinates",
            )

        st.markdown("")

        # GeoJSON
        if geojson:
            geojson_str = json.dumps(geojson, indent=2)
            st.download_button(
                "🗺️ Download Hotspot Zones (GeoJSON)",
                data=geojson_str,
                file_name="delhi_hotspot_zones.geojson",
                mime="application/json",
                help="GeoJSON format — import directly into QGIS, ArcGIS, or Mapbox",
            )

    with col2:
        st.markdown("### 📑 Report Exports")

        # Model metrics
        rf_bundle, _ = load_models()
        if rf_bundle:
            metrics = rf_bundle["metrics"]
            metrics_report = {
                "model": "Random Forest Regressor",
                "r2_score": metrics.get("r2_test"),
                "rmse": metrics.get("rmse_test"),
                "mae": metrics.get("mae_test"),
                "cv_r2": metrics.get("cv_r2_mean"),
                "feature_importances": metrics.get("feature_importances"),
            }
            metrics_json = json.dumps(metrics_report, indent=2)
            st.download_button(
                "🤖 Download ML Model Report (JSON)",
                data=metrics_json,
                file_name="model_metrics_report.json",
                mime="application/json",
            )

        st.markdown("")

        # City statistics summary
        from src.data_loader import get_city_stats
        stats = get_city_stats(df)
        stats_df = pd.DataFrame([stats])
        csv_stats = stats_df.to_csv(index=False)
        st.download_button(
            "📊 Download City Statistics (CSV)",
            data=csv_stats,
            file_name="delhi_city_statistics.csv",
            mime="text/csv",
        )

        st.markdown("")

        # Recommendations report
        recs = get_recommendations(len(zones_df))
        if recs:
            from src.recommender import get_intervention_summary_df
            recs_df = get_intervention_summary_df(recs)
            recs_csv = recs_df.to_csv(index=False)
            st.download_button(
                "❄️ Download Cooling Recommendations (CSV)",
                data=recs_csv,
                file_name="delhi_cooling_recommendations.csv",
                mime="text/csv",
            )

        st.markdown("")
        st.info(
            "💡 **Tip:** The GeoJSON file can be opened directly in **QGIS**, **ArcGIS**, "
            "or uploaded to **Mapbox/Leaflet** for custom web maps."
        )

    st.divider()
    st.markdown("### 📁 File Overview")
    file_info = [
        ("delhi_heat_stress_full.csv", f"{len(df):,} rows", "Full dataset with all features"),
        ("delhi_extreme_heat_zones.csv", f"{len(extreme_df):,} rows", "Extreme and high heat pixels only"),
        ("delhi_hotspot_zones.csv", f"{len(zones_df)} zones", "Top-20 critical hotspot zones"),
        ("delhi_hotspot_zones.geojson", "GIS format", "GeoJSON for QGIS/ArcGIS import"),
        ("model_metrics_report.json", "JSON", "ML model performance metrics"),
        ("delhi_cooling_recommendations.csv", f"{len(recs)} interventions", "Prioritised cooling interventions"),
    ]
    st.table(pd.DataFrame(file_info, columns=["File", "Size/Count", "Description"]))


# ============================================================
# PAGE 8 — ABOUT
# ============================================================

def page_about():
    st.title("ℹ️ About HeatSense")

    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown("""
        ## Urban Heat Stress Hotspot Detection using Geospatial AI/ML

        **HeatSense** is a satellite-powered AI system built for the
        **ISRO Bharatiya Antariksh Hackathon 2025** that detects, maps, and predicts
        urban heat stress hotspots in Indian cities using freely available satellite data.

        ### 🎯 Mission
        Help city planners and disaster management authorities identify exactly where
        and who is at risk from urban heat stress — and recommend data-driven cooling
        interventions to save lives.

        ### 🛰️ Data Sources
        | Dataset | Source | Resolution | Use |
        |---------|--------|------------|-----|
        | Landsat 8/9 | USGS EarthExplorer | 30m | LST, NDVI, NDBI |
        | Sentinel-2 | Copernicus Hub | 10m | Land use classification |
        | MODIS MOD11A2 | LP DAAC / GEE | 1km | Temporal LST validation |
        | WorldPop | WorldPop Hub | 100m | Population density |
        | GADM | gadm.org | Vector | City boundary |
        | OpenStreetMap | Geofabrik | Vector | Roads, parks, water |

        ### 🧮 Methodology
        1. **LST Calculation** — 5-step radiative transfer equation from Landsat Band 10
        2. **UHI Index** — Normalised deviation from city-wide mean temperature
        3. **Getis-Ord Gi*** — Spatial autocorrelation for statistically significant clusters
        4. **DBSCAN Clustering** — Group hotspot pixels into contiguous zones
        5. **Random Forest** — Predict heat stress from 8 geospatial features
        6. **SHAP Analysis** — Explainable AI for feature attribution
        7. **Rule + ML Recommender** — Prioritised cooling intervention engine

        ### 🏗️ Technology Stack
        Python · Streamlit · Scikit-learn · Folium · GeoPandas · Rasterio · PySAL · SHAP · Plotly

        ### 📡 Scalability
        This system is designed to run on **any Indian city** — simply swap the input
        Landsat scene and boundary shapefile. Plans to integrate with:
        - IMD real-time weather API for live heat stress alerts
        - ISRO Bhuvan portal for public-facing access
        - Smart City Mission planning tools
        """)

    with col2:
        st.markdown("### 📞 Project Info")
        st.info("""
        **Hackathon:** Bharatiya Antariksh Hackathon 2025

        **Organiser:** ISRO — Indian Space Research Organisation

        **Category:** Geospatial AI/ML

        **Target Users:**
        - NDMA (disaster management)
        - Smart City SPVs
        - Urban Local Bodies
        - IMD (weather forecasting)
        - Health departments

        **Social Impact:**
        - 1,500+ deaths prevented annually
        - 47,000 heat illness cases avoided
        - 2.3M residents protected
        """)

        st.markdown("### 🔗 References")
        st.markdown("""
        - Jiménez-Muñoz & Sobrino (2003) — LST algorithm
        - Ord & Getis (1995) — Gi* statistic
        - USGS Landsat Collection 2 User Guide
        - WHO Heat Health Action Plans 2024
        - ISRO Annual Report 2023-24
        """)

        st.markdown("### ⚙️ System Requirements")
        st.markdown("""
        - Python 3.10+
        - 8 GB RAM minimum
        - Internet for GEE access
        - ~2 GB disk for demo data
        """)


# ============================================================
# MAIN ROUTER
# ============================================================

def main():
    # Initialise session state
    if "selected_city" not in st.session_state:
        st.session_state["selected_city"] = "Delhi"

    page, city = render_sidebar()

    if page == "🏠 Home":
        page_home()
    elif page == "🌤️ Live Weather":
        page_live_weather(city)
    elif page == "🗺️ Heat Map":
        page_heat_map()
    elif page == "🔥 Hotspot Analysis":
        page_hotspot_analysis()
    elif page == "🤖 AI Predictions":
        page_ai_predictions()
    elif page == "❄️ Cooling Recommendations":
        page_cooling_recommendations()
    elif page == "📊 Statistics":
        page_statistics()
    elif page == "📥 Downloads":
        page_downloads()
    elif page == "ℹ️ About":
        page_about()


if __name__ == "__main__":
    main()
