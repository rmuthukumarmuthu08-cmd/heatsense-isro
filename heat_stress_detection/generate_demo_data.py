"""
generate_demo_data.py — One-time script to generate all demo data and train models.

Run this ONCE before launching the Streamlit app:
    python generate_demo_data.py

What it does:
    1. Generates 8000-point synthetic Delhi heat stress dataset
    2. Runs full hotspot detection pipeline (Gi* + DBSCAN)
    3. Trains Random Forest + Gradient Boosting models
    4. Saves all outputs to data/demo/ and models/

Expected runtime: 2-4 minutes on a standard laptop
Expected outputs:
    data/demo/delhi_heat_stress.csv       — main dataset (8000 rows)
    data/demo/hotspot_zones.csv           — top-20 hotspot zones
    data/demo/hotspot_zones.geojson       — GeoJSON for map layers
    models/heat_stress_rf.pkl             — trained Random Forest
    models/heat_stress_gb.pkl             — trained Gradient Boosting
"""

import json
import logging
import os
import sys
import time

# Add project root to Python path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------
DATA_DEMO_DIR = os.path.join(PROJECT_ROOT, "data", "demo")
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
os.makedirs(DATA_DEMO_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)


def main():
    t0 = time.time()
    logger.info("=" * 60)
    logger.info("Urban Heat Stress — Demo Data Generator")
    logger.info("Target City: Delhi | Data Year: 2023")
    logger.info("=" * 60)

    # ── Step 1: Generate synthetic data ───────────────────────────────────
    logger.info("\n[STEP 1/4] Generating synthetic Delhi dataset...")
    from src.preprocessing import generate_delhi_demo_data
    df = generate_delhi_demo_data(n_points=8000, seed=42)
    logger.info(f"  ✓ Generated {len(df)} sample points")
    logger.info(f"  ✓ LST range: {df['LST'].min():.1f}°C – {df['LST'].max():.1f}°C")
    logger.info(f"  ✓ Heat zones: {df['heat_zone'].value_counts().to_dict()}")

    # ── Step 2: Run hotspot detection pipeline ────────────────────────────
    logger.info("\n[STEP 2/4] Running hotspot detection pipeline...")
    from src.hotspot_detector import run_full_hotspot_pipeline
    df_annotated, hotspot_zones, geojson = run_full_hotspot_pipeline(df, top_n=20)
    logger.info(f"  ✓ Hotspot detection complete")
    logger.info(f"  ✓ Total hotspot pixels: {df_annotated['is_hotspot'].sum()}")
    logger.info(f"  ✓ Hotspot zones identified: {len(hotspot_zones)}")

    # Merge hotspot columns back to main df
    df = df_annotated.copy()

    # ── Step 3: Train ML models ────────────────────────────────────────────
    logger.info("\n[STEP 3/4] Training ML models...")
    from src.ml_model import train_full_pipeline
    ml_results = train_full_pipeline(df)
    logger.info(f"  ✓ Random Forest R² = {ml_results['rf_metrics']['r2_test']:.3f}")
    logger.info(f"  ✓ Random Forest RMSE = {ml_results['rf_metrics']['rmse_test']:.4f}")
    logger.info(f"  ✓ Gradient Boosting Accuracy = {ml_results['gb_metrics']['accuracy']:.3f}")
    logger.info(f"  ✓ 5-Fold CV R² = {ml_results['rf_metrics']['cv_r2_mean']:.3f} ± {ml_results['rf_metrics']['cv_r2_std']:.3f}")

    # ── Step 4: Save all outputs ──────────────────────────────────────────
    logger.info("\n[STEP 4/4] Saving outputs...")

    # Main dataset
    csv_path = os.path.join(DATA_DEMO_DIR, "delhi_heat_stress.csv")
    df.to_csv(csv_path, index=False)
    logger.info(f"  ✓ Main dataset saved: {csv_path}")

    # Hotspot zones CSV
    if not hotspot_zones.empty:
        hz_path = os.path.join(DATA_DEMO_DIR, "hotspot_zones.csv")
        hotspot_zones.to_csv(hz_path, index=False)
        logger.info(f"  ✓ Hotspot zones saved: {hz_path}")

    # Hotspot GeoJSON
    geojson_path = os.path.join(DATA_DEMO_DIR, "hotspot_zones.geojson")
    with open(geojson_path, "w") as f:
        json.dump(geojson, f, indent=2)
    logger.info(f"  ✓ GeoJSON saved: {geojson_path}")

    # Save SHAP values
    shap_path = os.path.join(DATA_DEMO_DIR, "shap_values.csv")
    ml_results["shap_df"].to_csv(shap_path, index=False)
    logger.info(f"  ✓ SHAP values saved: {shap_path}")

    # Save model metrics summary
    metrics_summary = {
        "rf_r2": ml_results["rf_metrics"]["r2_test"],
        "rf_rmse": ml_results["rf_metrics"]["rmse_test"],
        "rf_mae": ml_results["rf_metrics"]["mae_test"],
        "rf_cv_r2": ml_results["rf_metrics"]["cv_r2_mean"],
        "gb_accuracy": ml_results["gb_metrics"]["accuracy"],
        "feature_importances": ml_results["rf_metrics"]["feature_importances"],
    }
    import json as json_module
    metrics_path = os.path.join(DATA_DEMO_DIR, "model_metrics.json")
    with open(metrics_path, "w") as f:
        json_module.dump(metrics_summary, f, indent=2)
    logger.info(f"  ✓ Model metrics saved: {metrics_path}")

    elapsed = time.time() - t0
    logger.info("\n" + "=" * 60)
    logger.info(f"✅ Demo data generation COMPLETE in {elapsed:.1f} seconds")
    logger.info("")
    logger.info("Summary:")
    logger.info(f"  • Dataset:    {len(df):,} points over Delhi")
    logger.info(f"  • Hotspots:   {len(hotspot_zones)} critical zones identified")
    logger.info(f"  • ML Model:   Random Forest R² = {ml_results['rf_metrics']['r2_test']:.3f}")
    logger.info(f"  • Pop at risk: {df[df['heat_zone'].isin(['Extreme','High'])]['pop_density'].sum():,.0f}")
    logger.info("")
    logger.info("Next step: Run the Streamlit dashboard:")
    logger.info("   streamlit run app.py")
    logger.info("=" * 60)


if __name__ == "__main__":
    import traceback
    try:
        main()
    except Exception as exc:
        print("\n" + "=" * 60)
        print("[FATAL ERROR] generate_demo_data.py crashed:")
        traceback.print_exc()
        print("=" * 60)
        sys.exit(1)
