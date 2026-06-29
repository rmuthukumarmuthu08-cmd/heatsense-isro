"""
test_lst.py — Unit Tests for LST Calculation and Hotspot Detection

Run: python -m pytest tests/ -v
Expected: All tests PASS in < 30 seconds
"""

import sys
import os
import numpy as np
import pandas as pd
import pytest

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.lst_calculator import (
    dn_to_radiance,
    radiance_to_bt,
    calculate_ndvi,
    calculate_lse,
    calculate_lst,
    calculate_uhi_index,
    classify_heat_zones,
    get_lst_statistics,
)
from src.preprocessing import generate_delhi_demo_data, _classify_uhi_vectorised
from src.hotspot_detector import (
    detect_hotspots_gistar,
    calculate_severity_scores,
    identify_top_hotspots,
)
from src.ml_model import prepare_features, train_random_forest


# ─────────────────────────────────────────────────────────────
# LST Calculator Tests
# ─────────────────────────────────────────────────────────────

class TestDNToRadiance:
    def test_basic_conversion(self):
        dn = np.array([1000, 2000, 3000])
        result = dn_to_radiance(dn, mult=0.0003342, add=-0.09767)
        assert result.shape == dn.shape

    def test_linear_relationship(self):
        dn = np.array([0, 1000])
        mult, add = 0.0003342, -0.09767
        result = dn_to_radiance(dn, mult, add)
        assert abs(result[1] - result[0] - mult * 1000) < 1e-6

    def test_typical_range(self):
        """Landsat Band 10 typical DN range 22000-28000 → radiance 5-10 W/m²/sr/µm"""
        dn = np.array([22000, 28000])
        result = dn_to_radiance(dn, mult=0.0003342, add=-0.09767)
        assert 4 < result[0] < 8
        assert 6 < result[1] < 10


class TestRadianceToBT:
    def test_output_in_celsius(self):
        radiance = np.array([6.0, 8.0, 10.0])
        bt = radiance_to_bt(radiance)
        # Delhi summer BT should be 15–60°C range
        assert np.all(bt > 0) and np.all(bt < 80)

    def test_monotonic_increase(self):
        """Higher radiance → higher BT"""
        radiance = np.array([5.0, 7.0, 9.0])
        bt = radiance_to_bt(radiance)
        assert bt[0] < bt[1] < bt[2]

    def test_zero_radiance_returns_nan(self):
        radiance = np.array([0.0, 5.0])
        bt = radiance_to_bt(radiance)
        assert np.isnan(bt[0])
        assert not np.isnan(bt[1])


class TestNDVI:
    def test_vegetation_positive(self):
        red = np.array([0.05])
        nir = np.array([0.40])
        ndvi = calculate_ndvi(red, nir)
        assert ndvi[0] > 0.2

    def test_water_negative(self):
        red = np.array([0.1])
        nir = np.array([0.02])
        ndvi = calculate_ndvi(red, nir)
        assert ndvi[0] < 0.0

    def test_range_clipped(self):
        red = np.random.rand(100)
        nir = np.random.rand(100)
        ndvi = calculate_ndvi(red, nir)
        assert np.all(ndvi >= -1.0) and np.all(ndvi <= 1.0)

    def test_zero_denominator(self):
        red = np.array([0.0])
        nir = np.array([0.0])
        ndvi = calculate_ndvi(red, nir)
        assert np.isnan(ndvi[0])


class TestLSE:
    def test_bare_soil_emissivity(self):
        ndvi = np.array([0.1, 0.15])  # Below NDVIs=0.2
        lse = calculate_lse(ndvi)
        np.testing.assert_array_equal(lse, 0.97)

    def test_full_vegetation_emissivity(self):
        ndvi = np.array([0.6, 0.8])  # Above NDVIv=0.5
        lse = calculate_lse(ndvi)
        np.testing.assert_array_equal(lse, 0.99)

    def test_mixed_pixel_range(self):
        ndvi = np.array([0.35])  # Between 0.2 and 0.5
        lse = calculate_lse(ndvi)
        assert 0.97 < lse[0] < 0.99


class TestLST:
    def test_realistic_range(self):
        """LST for Indian summer city should be 25–55°C"""
        bt = np.array([30.0, 40.0, 50.0])
        lse = np.array([0.97, 0.98, 0.99])
        lst = calculate_lst(bt, lse)
        assert np.all(lst > 20) and np.all(lst < 65)

    def test_higher_emissivity_lower_lst(self):
        """Higher emissivity → lower LST for same BT"""
        bt = np.array([40.0, 40.0])
        lse = np.array([0.97, 0.99])
        lst = calculate_lst(bt, lse)
        assert lst[0] > lst[1]


class TestUHI:
    def test_mean_zero(self):
        """UHI index should have mean ≈ 0"""
        lst = np.random.normal(40, 5, 1000)
        uhi = calculate_uhi_index(lst)
        assert abs(uhi.mean()) < 0.01

    def test_std_one(self):
        """UHI index should have std ≈ 1"""
        lst = np.random.normal(40, 5, 1000)
        uhi = calculate_uhi_index(lst)
        assert abs(uhi.std() - 1.0) < 0.01

    def test_classification_coverage(self):
        """All 5 zone labels should appear"""
        uhi = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
        zones = classify_heat_zones(uhi)
        assert set(zones) == {"Very Low", "Low", "Moderate", "High", "Extreme"}

    def test_extreme_threshold(self):
        uhi = np.array([1.6, -1.6, 0.0])
        zones = classify_heat_zones(uhi)
        assert zones[0] == "Extreme"
        assert zones[1] == "Very Low"
        assert zones[2] == "Moderate"


# ─────────────────────────────────────────────────────────────
# Preprocessing Tests
# ─────────────────────────────────────────────────────────────

class TestDemoDataGenerator:
    @pytest.fixture(scope="class")
    def demo_df(self):
        return generate_delhi_demo_data(n_points=500, seed=42)

    def test_shape(self, demo_df):
        assert len(demo_df) == 500

    def test_required_columns(self, demo_df):
        required = ["lat", "lon", "LST", "NDVI", "NDBI", "NDWI",
                    "UHI_index", "heat_zone", "pop_density",
                    "dist_water", "elevation", "imperv_fraction",
                    "heat_stress_index", "land_use"]
        for col in required:
            assert col in demo_df.columns, f"Missing column: {col}"

    def test_lst_range(self, demo_df):
        assert demo_df["LST"].min() >= 25.0
        assert demo_df["LST"].max() <= 55.0

    def test_ndvi_range(self, demo_df):
        assert demo_df["NDVI"].min() >= -0.2
        assert demo_df["NDVI"].max() <= 0.85

    def test_heat_zone_values(self, demo_df):
        valid_zones = {"Very Low", "Low", "Moderate", "High", "Extreme"}
        assert set(demo_df["heat_zone"].unique()).issubset(valid_zones)

    def test_heat_stress_range(self, demo_df):
        assert demo_df["heat_stress_index"].min() >= 0.0
        assert demo_df["heat_stress_index"].max() <= 1.0

    def test_delhi_bounds(self, demo_df):
        assert demo_df["lat"].min() >= 28.3
        assert demo_df["lat"].max() <= 29.0
        assert demo_df["lon"].min() >= 76.7
        assert demo_df["lon"].max() <= 77.5

    def test_reproducible(self):
        df1 = generate_delhi_demo_data(n_points=100, seed=99)
        df2 = generate_delhi_demo_data(n_points=100, seed=99)
        pd.testing.assert_frame_equal(df1, df2)

    def test_extreme_zones_exist(self, demo_df):
        assert (demo_df["heat_zone"] == "Extreme").sum() > 0


# ─────────────────────────────────────────────────────────────
# Hotspot Detector Tests
# ─────────────────────────────────────────────────────────────

class TestHotspotDetector:
    @pytest.fixture(scope="class")
    def annotated_df(self):
        df = generate_delhi_demo_data(n_points=1000, seed=7)
        df = detect_hotspots_gistar(df, radius_deg=0.04)
        return df

    def test_gistar_columns_added(self, annotated_df):
        assert "gi_z_score" in annotated_df.columns
        assert "is_hotspot" in annotated_df.columns
        assert "is_coldspot" in annotated_df.columns

    def test_hotspots_detected(self, annotated_df):
        """At least some hotspots should be detected"""
        assert annotated_df["is_hotspot"].sum() > 0

    def test_gistar_and_hotspot_consistency(self, annotated_df):
        """Hotspot pixels should have z_score > 1.96"""
        hotspots = annotated_df[annotated_df["is_hotspot"]]
        assert (hotspots["gi_z_score"] > 1.96).all()

    def test_severity_score_range(self):
        df = generate_delhi_demo_data(n_points=500, seed=3)
        df = calculate_severity_scores(df)
        assert df["hotspot_score"].min() >= 0.0
        assert df["hotspot_score"].max() <= 1.0

    def test_identify_hotspots_output(self):
        df = generate_delhi_demo_data(n_points=2000, seed=5)
        df = detect_hotspots_gistar(df)
        df = calculate_severity_scores(df)
        from src.hotspot_detector import cluster_hotspots_dbscan
        df = cluster_hotspots_dbscan(df)
        zones = identify_top_hotspots(df, top_n=10)
        if not zones.empty:
            assert "rank" in zones.columns
            assert "zone_name" in zones.columns
            assert "mean_LST" in zones.columns
            assert "total_population" in zones.columns


# ─────────────────────────────────────────────────────────────
# ML Model Tests
# ─────────────────────────────────────────────────────────────

class TestMLModel:
    @pytest.fixture(scope="class")
    def ml_data(self):
        df = generate_delhi_demo_data(n_points=1000, seed=42)
        return prepare_features(df)

    def test_feature_matrix_shape(self, ml_data):
        X_train = ml_data["X_train"]
        assert X_train.ndim == 2
        assert X_train.shape[1] == 8  # 8 features

    def test_train_test_split(self, ml_data):
        n_train = len(ml_data["X_train"])
        n_test = len(ml_data["X_test"])
        assert abs(n_train / (n_train + n_test) - 0.8) < 0.02

    def test_random_forest_trains(self, ml_data):
        rf, metrics = train_random_forest(ml_data, n_estimators=10)
        assert metrics["r2_test"] > 0.0  # Should at least be positive
        assert "rmse_test" in metrics
        assert "feature_importances" in metrics

    def test_feature_importances_sum_to_one(self, ml_data):
        rf, metrics = train_random_forest(ml_data, n_estimators=10)
        total = sum(metrics["feature_importances"].values())
        assert abs(total - 1.0) < 0.01

    def test_rf_achieves_good_r2(self, ml_data):
        """RF should achieve R² > 0.70 on this synthetic dataset"""
        rf, metrics = train_random_forest(ml_data, n_estimators=50)
        assert metrics["r2_test"] > 0.70, f"R²={metrics['r2_test']:.3f} is below threshold 0.70"


# ─────────────────────────────────────────────────────────────
# Integration Test
# ─────────────────────────────────────────────────────────────

def test_full_pipeline_integration():
    """
    End-to-end integration test:
    Data Generation → LST Calc → Hotspot Detection → ML Training
    """
    # 1. Generate data
    df = generate_delhi_demo_data(n_points=500, seed=0)
    assert len(df) == 500

    # 2. LST statistics
    stats = get_lst_statistics(df)
    assert stats["mean_lst"] > 25
    assert stats["extreme_pct"] >= 0

    # 3. Hotspot detection
    df = detect_hotspots_gistar(df, radius_deg=0.05)
    df = calculate_severity_scores(df)
    assert "hotspot_score" in df.columns

    # 4. ML feature preparation
    data = prepare_features(df)
    assert data["X_train"].shape[0] > 0

    print("\n✅ Full pipeline integration test PASSED")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
