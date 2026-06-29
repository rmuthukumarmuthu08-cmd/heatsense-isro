"""
app.py — HeatSense Diagnostic Mode
Temporary diagnostic to identify exact failure point on Streamlit Cloud.
"""
import sys
import os
import traceback

import streamlit as st

st.set_page_config(page_title="HeatSense Diagnostic", page_icon="🔍", layout="wide")
st.title("🔍 HeatSense — Deployment Diagnostic")
st.write(f"**Python:** {sys.version}")
st.write(f"**Platform:** {sys.platform}")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
st.write(f"**PROJECT_ROOT:** `{PROJECT_ROOT}`")
st.write(f"**Writable?** {os.access(PROJECT_ROOT, os.W_OK)}")

# ── Test 1: Core imports ──────────────────────────────────────────────────
st.subheader("1. Core Package Imports")
try:
    import numpy as np
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go
    import matplotlib
    import joblib
    import sklearn
    st.success(f"✅ numpy {np.__version__} | pandas {pd.__version__} | plotly {px.__version__} | sklearn {sklearn.__version__}")
except Exception as e:
    st.error(f"❌ FAILED: {e}")
    st.code(traceback.format_exc())

# ── Test 2: Streamlit-folium ─────────────────────────────────────────────
st.subheader("2. Folium / Streamlit-Folium")
try:
    import folium
    from streamlit_folium import st_folium
    st.success(f"✅ folium {folium.__version__}")
except Exception as e:
    st.error(f"❌ FAILED: {e}")
    st.code(traceback.format_exc())

# ── Test 3: File write ────────────────────────────────────────────────────
st.subheader("3. File System Write Access")
try:
    data_dir = os.path.join(PROJECT_ROOT, "data", "demo")
    models_dir = os.path.join(PROJECT_ROOT, "models")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(models_dir, exist_ok=True)
    test_path = os.path.join(data_dir, "test_write.txt")
    with open(test_path, "w") as f:
        f.write("write_test_ok")
    os.remove(test_path)
    st.success(f"✅ Can write to `{data_dir}`")
except Exception as e:
    st.error(f"❌ FAILED: {e}")
    st.code(traceback.format_exc())

# ── Test 4: src imports ───────────────────────────────────────────────────
st.subheader("4. src Module Imports")
sys.path.insert(0, PROJECT_ROOT)

for mod_name, fn_name in [
    ("src.preprocessing", "generate_delhi_demo_data"),
    ("src.hotspot_detector", "run_full_hotspot_pipeline"),
    ("src.ml_model", "train_full_pipeline"),
    ("src.data_loader", "load_demo_data"),
    ("src.recommender", "generate_recommendations"),
    ("src.live_data", "get_live_city_weather"),
    ("src.visualizer", "create_lst_heatmap"),
]:
    try:
        mod = __import__(mod_name, fromlist=[fn_name])
        fn = getattr(mod, fn_name)
        st.success(f"✅ `{mod_name}.{fn_name}`")
    except Exception as e:
        st.error(f"❌ `{mod_name}.{fn_name}` — {e}")
        st.code(traceback.format_exc())

# ── Test 5: Data generation ───────────────────────────────────────────────
st.subheader("5. Data Generation (small test)")
try:
    from src.preprocessing import generate_delhi_demo_data
    df = generate_delhi_demo_data(n_points=100, random_state=42)
    st.success(f"✅ Generated {len(df)} rows, cols: {list(df.columns[:5])}")
except Exception as e:
    st.error(f"❌ FAILED: {e}")
    st.code(traceback.format_exc())

# ── Test 6: Hotspot pipeline ──────────────────────────────────────────────
st.subheader("6. Hotspot Pipeline (100 pts)")
try:
    from src.hotspot_detector import run_full_hotspot_pipeline
    ann_df, zones, geojson = run_full_hotspot_pipeline(df)
    st.success(f"✅ {len(zones)} zones, {len(geojson['features'])} geojson features")
except Exception as e:
    st.error(f"❌ FAILED: {e}")
    st.code(traceback.format_exc())

# ── Test 7: ML pipeline ───────────────────────────────────────────────────
st.subheader("7. ML Training (100 pts)")
try:
    from src.ml_model import train_full_pipeline
    results = train_full_pipeline(df)
    st.success(f"✅ RF r²={results['rf_metrics']['r2_test']:.3f}")
except Exception as e:
    st.error(f"❌ FAILED: {e}")
    st.code(traceback.format_exc())

st.divider()
st.balloons()
st.success("**Diagnostic complete!** All steps shown above. Fix any ❌ items.")
