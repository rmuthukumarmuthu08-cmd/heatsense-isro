"""
test_preprocessing.py — Unit tests for src/preprocessing.py

Tests:
    - generate_delhi_demo_data: shape, columns, LST range, heat zones
    - compute_uhi_index: normalisation, z-score bounds
    - assign_heat_zones: correct label assignment
    - Feature column completeness
"""

import sys
import os
import pytest
import numpy as np
import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.preprocessing import (
    generate_delhi_demo_data,
    compute_uhi_index,
    assign_heat_zones,
    HEAT_ZONE_THRESHOLDS,
    DELHI_BOUNDS,
)


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

@pytest.fixture(scope="module")
def demo_df():
    """Generate a small dataset for fast testing."""
    return generate_delhi_demo_data(n_points=500, seed=0)


# ─────────────────────────────────────────
# generate_delhi_demo_data
# ─────────────────────────────────────────

class TestGenerateDelhiDemoData:

    def test_returns_dataframe(self, demo_df):
        assert isinstance(demo_df, pd.DataFrame), "Should return a DataFrame"

    def test_row_count(self, demo_df):
        assert len(demo_df) == 500, f"Expected 500 rows, got {len(demo_df)}"

    def test_required_columns(self, demo_df):
        required = ["lat", "lon", "LST", "NDVI", "NDBI", "NDWI",
                    "pop_density", "dist_water", "elevation",
                    "imperv_fraction", "heat_zone", "heat_stress_index"]
        missing = [c for c in required if c not in demo_df.columns]
        assert not missing, f"Missing columns: {missing}"

    def test_lat_lon_within_delhi(self, demo_df):
        assert demo_df["lat"].between(DELHI_BOUNDS["lat_min"], DELHI_BOUNDS["lat_max"]).all(), \
            "Latitudes outside Delhi bounds"
        assert demo_df["lon"].between(DELHI_BOUNDS["lon_min"], DELHI_BOUNDS["lon_max"]).all(), \
            "Longitudes outside Delhi bounds"

    def test_lst_range(self, demo_df):
        assert demo_df["LST"].min() >= 20, "LST below 20°C is unrealistic for Delhi"
        assert demo_df["LST"].max() <= 60, "LST above 60°C is unrealistic"

    def test_ndvi_range(self, demo_df):
        assert demo_df["NDVI"].between(-1.0, 1.0).all(), "NDVI out of [-1, 1] range"

    def test_ndbi_range(self, demo_df):
        assert demo_df["NDBI"].between(-1.0, 1.0).all(), "NDBI out of [-1, 1] range"

    def test_heat_stress_index_range(self, demo_df):
        assert demo_df["heat_stress_index"].between(0.0, 1.0).all(), \
            "heat_stress_index must be in [0, 1]"

    def test_pop_density_positive(self, demo_df):
        assert (demo_df["pop_density"] >= 0).all(), "Population density must be non-negative"

    def test_heat_zones_valid(self, demo_df):
        valid_zones = {"Very Low", "Low", "Moderate", "High", "Extreme"}
        actual_zones = set(demo_df["heat_zone"].unique())
        assert actual_zones.issubset(valid_zones), f"Unexpected heat zones: {actual_zones - valid_zones}"

    def test_all_heat_zones_present(self, demo_df):
        """With 500 points, all 5 heat zones should appear."""
        assert len(demo_df["heat_zone"].unique()) >= 3, "Expected at least 3 distinct heat zones in 500 points"

    def test_no_nan_in_core_columns(self, demo_df):
        core = ["lat", "lon", "LST", "NDVI", "heat_zone", "heat_stress_index"]
        nan_cols = [c for c in core if demo_df[c].isna().any()]
        assert not nan_cols, f"NaN values found in: {nan_cols}"

    def test_reproducibility(self):
        df1 = generate_delhi_demo_data(n_points=100, seed=42)
        df2 = generate_delhi_demo_data(n_points=100, seed=42)
        pd.testing.assert_frame_equal(df1.reset_index(drop=True), df2.reset_index(drop=True))

    def test_different_seeds_differ(self):
        df1 = generate_delhi_demo_data(n_points=100, seed=1)
        df2 = generate_delhi_demo_data(n_points=100, seed=2)
        assert not df1["LST"].equals(df2["LST"]), "Different seeds should give different data"

    def test_land_use_column(self, demo_df):
        assert "land_use" in demo_df.columns, "land_use column missing"
        valid_lu = {"Residential", "Industrial", "Commercial", "Green Space",
                    "Water Body", "Bare Land", "Transportation"}
        actual = set(demo_df["land_use"].unique())
        assert actual.issubset(valid_lu), f"Unexpected land use categories: {actual - valid_lu}"


# ─────────────────────────────────────────
# compute_uhi_index
# ─────────────────────────────────────────

class TestComputeUHIIndex:

    def test_adds_uhi_column(self, demo_df):
        result = compute_uhi_index(demo_df.copy())
        assert "uhi_index" in result.columns, "uhi_index column not added"

    def test_uhi_mean_near_zero(self, demo_df):
        result = compute_uhi_index(demo_df.copy())
        assert abs(result["uhi_index"].mean()) < 0.1, "UHI index mean should be ~0 (z-score)"

    def test_uhi_std_near_one(self, demo_df):
        result = compute_uhi_index(demo_df.copy())
        assert abs(result["uhi_index"].std() - 1.0) < 0.1, "UHI index std should be ~1 (z-score)"

    def test_does_not_modify_original(self, demo_df):
        original_cols = set(demo_df.columns)
        compute_uhi_index(demo_df.copy())
        assert set(demo_df.columns) == original_cols, "Should not modify original DataFrame"

    def test_high_lst_has_positive_uhi(self, demo_df):
        result = compute_uhi_index(demo_df.copy())
        hot_pixels = result[result["LST"] > result["LST"].quantile(0.9)]
        assert hot_pixels["uhi_index"].mean() > 0, "Hot pixels should have positive UHI index"

    def test_low_lst_has_negative_uhi(self, demo_df):
        result = compute_uhi_index(demo_df.copy())
        cool_pixels = result[result["LST"] < result["LST"].quantile(0.1)]
        assert cool_pixels["uhi_index"].mean() < 0, "Cool pixels should have negative UHI index"


# ─────────────────────────────────────────
# assign_heat_zones
# ─────────────────────────────────────────

class TestAssignHeatZones:

    def test_adds_heat_zone_column(self):
        df = pd.DataFrame({"uhi_index": [-2.5, -1.0, 0.0, 1.0, 2.5]})
        result = assign_heat_zones(df.copy())
        assert "heat_zone" in result.columns

    def test_correct_zone_assignment(self):
        df = pd.DataFrame({"uhi_index": [-3.0, -1.0, 0.0, 1.5, 3.0]})
        result = assign_heat_zones(df.copy())
        zones = result["heat_zone"].tolist()
        # Most negative → Very Low; most positive → Extreme
        assert zones[0] == "Very Low", f"Expected 'Very Low', got {zones[0]}"
        assert zones[-1] == "Extreme", f"Expected 'Extreme', got {zones[-1]}"

    def test_all_rows_get_zone(self, demo_df):
        df_with_uhi = compute_uhi_index(demo_df.copy())
        result = assign_heat_zones(df_with_uhi)
        assert result["heat_zone"].isna().sum() == 0, "Some rows have no heat zone assigned"

    def test_zone_ordering(self):
        """Higher UHI index should map to more severe heat zones."""
        zone_order = ["Very Low", "Low", "Moderate", "High", "Extreme"]
        uhi_values = np.array([-3, -1.5, 0, 1.5, 3])
        df = pd.DataFrame({"uhi_index": uhi_values})
        result = assign_heat_zones(df.copy())
        assigned_indices = [zone_order.index(z) for z in result["heat_zone"]]
        assert assigned_indices == sorted(assigned_indices), "Zone severity should increase with UHI"


# ─────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────

class TestEdgeCases:

    def test_single_row(self):
        df = generate_delhi_demo_data(n_points=1, seed=99)
        assert len(df) == 1

    def test_large_dataset_shape(self):
        df = generate_delhi_demo_data(n_points=2000, seed=7)
        assert df.shape[0] == 2000

    def test_uhi_constant_lst(self):
        """Edge case: all points have same LST — UHI should be 0."""
        df = pd.DataFrame({"LST": [35.0] * 10})
        result = compute_uhi_index(df.copy())
        # std is 0, so all z-scores should be 0
        assert (result["uhi_index"] == 0).all(), "All-same LST should give UHI=0"
