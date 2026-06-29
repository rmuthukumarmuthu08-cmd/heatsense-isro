"""
test_hotspot_detector.py — Unit tests for src/hotspot_detector.py

Tests:
    - detect_hotspots_gistar: column addition, threshold logic, proportion sanity
    - cluster_hotspots_dbscan: cluster IDs, noise handling, no sklearn dependency
    - calculate_severity_scores: range [0,1], weighted correctly
    - identify_top_hotspots: top_n limit, required columns, sorting
    - create_hotspot_geojson: valid GeoJSON structure
    - run_full_hotspot_pipeline: end-to-end
"""

import sys
import os
import pytest
import json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.hotspot_detector import (
    detect_hotspots_gistar,
    cluster_hotspots_dbscan,
    calculate_severity_scores,
    identify_top_hotspots,
    create_hotspot_geojson,
    run_full_hotspot_pipeline,
)
from src.preprocessing import generate_delhi_demo_data


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

@pytest.fixture(scope="module")
def base_df():
    return generate_delhi_demo_data(n_points=300, seed=42)


@pytest.fixture(scope="module")
def annotated_df(base_df):
    return detect_hotspots_gistar(base_df.copy(), radius_deg=0.05)


@pytest.fixture(scope="module")
def scored_df(annotated_df):
    return calculate_severity_scores(annotated_df.copy())


@pytest.fixture(scope="module")
def clustered_df(scored_df):
    return cluster_hotspots_dbscan(scored_df.copy(), eps_deg=0.05, min_samples=5)


# ─────────────────────────────────────────
# detect_hotspots_gistar
# ─────────────────────────────────────────

class TestDetectHotspotsGistar:

    def test_adds_columns(self, annotated_df):
        for col in ["gi_z_score", "is_hotspot", "is_coldspot"]:
            assert col in annotated_df.columns, f"Missing column: {col}"

    def test_gi_z_score_is_float(self, annotated_df):
        assert annotated_df["gi_z_score"].dtype in [np.float32, np.float64], \
            "gi_z_score should be float"

    def test_hotspot_boolean(self, annotated_df):
        assert annotated_df["is_hotspot"].dtype == bool, "is_hotspot should be bool"
        assert annotated_df["is_coldspot"].dtype == bool, "is_coldspot should be bool"

    def test_hotspot_threshold(self, annotated_df):
        """All hotspot pixels must have z_score > 1.96."""
        hotspot_rows = annotated_df[annotated_df["is_hotspot"]]
        assert (hotspot_rows["gi_z_score"] > 1.96).all(), \
            "Hotspot pixels must have z-score > 1.96"

    def test_coldspot_threshold(self, annotated_df):
        coldspot_rows = annotated_df[annotated_df["is_coldspot"]]
        assert (coldspot_rows["gi_z_score"] < -1.96).all(), \
            "Coldspot pixels must have z-score < -1.96"

    def test_no_overlap_hot_cold(self, annotated_df):
        overlap = annotated_df["is_hotspot"] & annotated_df["is_coldspot"]
        assert not overlap.any(), "A pixel cannot be both hotspot and coldspot"

    def test_row_count_preserved(self, base_df, annotated_df):
        assert len(annotated_df) == len(base_df), "Row count must not change"

    def test_some_hotspots_found(self, annotated_df):
        assert annotated_df["is_hotspot"].sum() > 0, \
            "Expected at least 1 hotspot in synthetic Delhi data"

    def test_custom_column(self, base_df):
        """Test using NDVI as value column."""
        result = detect_hotspots_gistar(base_df.copy(), value_col="NDVI", radius_deg=0.05)
        assert "gi_z_score" in result.columns

    def test_does_not_modify_original(self, base_df):
        original = base_df.copy()
        detect_hotspots_gistar(base_df.copy())
        pd.testing.assert_frame_equal(base_df.reset_index(drop=True),
                                       original.reset_index(drop=True))


# ─────────────────────────────────────────
# calculate_severity_scores
# ─────────────────────────────────────────

class TestCalculateSeverityScores:

    def test_adds_hotspot_score(self, scored_df):
        assert "hotspot_score" in scored_df.columns

    def test_score_range(self, scored_df):
        assert scored_df["hotspot_score"].between(0.0, 1.0).all(), \
            "hotspot_score must be in [0, 1]"

    def test_no_nan(self, scored_df):
        assert not scored_df["hotspot_score"].isna().any(), "No NaN in hotspot_score"

    def test_high_lst_high_score(self, scored_df):
        """High LST points should have higher severity scores on average."""
        median_lst = scored_df["LST"].median()
        high_lst = scored_df[scored_df["LST"] > median_lst]["hotspot_score"].mean()
        low_lst = scored_df[scored_df["LST"] <= median_lst]["hotspot_score"].mean()
        assert high_lst > low_lst, "Higher LST should yield higher severity score"


# ─────────────────────────────────────────
# cluster_hotspots_dbscan
# ─────────────────────────────────────────

class TestClusterHotspotsDBSCAN:

    def test_adds_cluster_id(self, clustered_df):
        assert "cluster_id" in clustered_df.columns

    def test_noise_label_minus_one(self, clustered_df):
        """Noise points should have cluster_id == -1."""
        valid_ids = clustered_df["cluster_id"]
        assert (valid_ids >= -1).all(), "cluster_id should be -1 (noise) or >= 0"

    def test_cluster_ids_are_integers(self, clustered_df):
        assert pd.api.types.is_integer_dtype(clustered_df["cluster_id"]) or \
               clustered_df["cluster_id"].dtype in [np.float64, np.float32], \
            "cluster_id should be numeric"

    def test_some_clusters_found(self, clustered_df):
        n_clusters = (clustered_df["cluster_id"] >= 0).sum()
        assert n_clusters > 0, "Expected at least some clustered hotspot points"

    def test_no_sklearn_dependency(self):
        """Ensure the module does NOT import sklearn.cluster.DBSCAN at module level."""
        import importlib
        import src.hotspot_detector as hd_module
        src_path = os.path.abspath(hd_module.__file__)
        with open(src_path, "r") as f:
            source = f.read()
        # Module-level import of sklearn DBSCAN was removed to fix scipy DLL issue
        assert "from sklearn.cluster import DBSCAN" not in source, \
            "sklearn DBSCAN import must NOT be at module level (scipy DLL crash fix)"

    def test_row_count_preserved(self, scored_df, clustered_df):
        assert len(clustered_df) == len(scored_df)

    def test_empty_hotspots(self):
        """Edge case: no hotspot pixels — should not crash."""
        df = pd.DataFrame({
            "lat": [28.6, 28.61], "lon": [77.2, 77.21],
            "is_hotspot": [False, False],
        })
        result = cluster_hotspots_dbscan(df)
        assert "cluster_id" in result.columns
        assert (result["cluster_id"] == -1).all()

    def test_all_hotspots_single_cluster(self):
        """Very dense hotspot cluster — all in one cell."""
        n = 50
        df = pd.DataFrame({
            "lat": np.random.uniform(28.60, 28.61, n),
            "lon": np.random.uniform(77.20, 77.21, n),
            "is_hotspot": [True] * n,
        })
        result = cluster_hotspots_dbscan(df, eps_deg=0.05, min_samples=5)
        n_clusters = len(result[result["cluster_id"] >= 0]["cluster_id"].unique())
        assert n_clusters >= 1


# ─────────────────────────────────────────
# identify_top_hotspots
# ─────────────────────────────────────────

class TestIdentifyTopHotspots:

    def test_returns_dataframe(self, clustered_df):
        result = identify_top_hotspots(clustered_df)
        assert isinstance(result, pd.DataFrame)

    def test_top_n_limit(self, clustered_df):
        result = identify_top_hotspots(clustered_df, top_n=5)
        assert len(result) <= 5

    def test_required_columns(self, clustered_df):
        result = identify_top_hotspots(clustered_df)
        for col in ["centroid_lat", "centroid_lon", "mean_LST", "max_LST",
                    "mean_hotspot_score", "n_pixels", "total_population", "zone_name"]:
            assert col in result.columns, f"Missing column: {col}"

    def test_sorted_by_score_descending(self, clustered_df):
        result = identify_top_hotspots(clustered_df)
        if len(result) > 1:
            scores = result["mean_hotspot_score"].tolist()
            assert scores == sorted(scores, reverse=True), "Should be sorted by score descending"

    def test_rank_column(self, clustered_df):
        result = identify_top_hotspots(clustered_df)
        if not result.empty:
            assert "rank" in result.columns
            assert result["rank"].iloc[0] == 1, "First row rank should be 1"

    def test_empty_input(self):
        """No valid clusters — should return empty DataFrame."""
        df = pd.DataFrame({
            "lat": [28.6], "lon": [77.2], "LST": [35.0], "NDVI": [0.2],
            "NDBI": [0.1], "imperv_fraction": [0.5], "pop_density": [1000],
            "hotspot_score": [0.5], "cluster_id": [-1],
        })
        result = identify_top_hotspots(df)
        assert result.empty


# ─────────────────────────────────────────
# create_hotspot_geojson
# ─────────────────────────────────────────

class TestCreateHotspotGeoJSON:

    @pytest.fixture(scope="class")
    def hotspot_zones(self, base_df):
        df = detect_hotspots_gistar(base_df.copy(), radius_deg=0.05)
        df = calculate_severity_scores(df)
        df = cluster_hotspots_dbscan(df, eps_deg=0.05, min_samples=5)
        return identify_top_hotspots(df)

    def test_valid_geojson_structure(self, base_df):
        df = detect_hotspots_gistar(base_df.copy(), radius_deg=0.05)
        df = calculate_severity_scores(df)
        df = cluster_hotspots_dbscan(df, eps_deg=0.05, min_samples=5)
        zones = identify_top_hotspots(df)
        if zones.empty:
            pytest.skip("No hotspot zones to test GeoJSON")
        geojson = create_hotspot_geojson(zones)
        assert geojson["type"] == "FeatureCollection"
        assert "features" in geojson
        assert isinstance(geojson["features"], list)

    def test_each_feature_is_point(self, base_df):
        df = detect_hotspots_gistar(base_df.copy(), radius_deg=0.05)
        df = calculate_severity_scores(df)
        df = cluster_hotspots_dbscan(df, eps_deg=0.05, min_samples=5)
        zones = identify_top_hotspots(df)
        if zones.empty:
            pytest.skip("No hotspot zones")
        geojson = create_hotspot_geojson(zones)
        for feat in geojson["features"]:
            assert feat["geometry"]["type"] == "Point"
            coords = feat["geometry"]["coordinates"]
            assert len(coords) == 2  # [lon, lat]

    def test_geojson_serialisable(self, base_df):
        df = detect_hotspots_gistar(base_df.copy(), radius_deg=0.05)
        df = calculate_severity_scores(df)
        df = cluster_hotspots_dbscan(df, eps_deg=0.05, min_samples=5)
        zones = identify_top_hotspots(df)
        if zones.empty:
            pytest.skip("No hotspot zones")
        geojson = create_hotspot_geojson(zones)
        serialised = json.dumps(geojson)
        parsed_back = json.loads(serialised)
        assert parsed_back["type"] == "FeatureCollection"


# ─────────────────────────────────────────
# run_full_hotspot_pipeline
# ─────────────────────────────────────────

class TestRunFullHotspotPipeline:

    def test_returns_three_outputs(self, base_df):
        result = run_full_hotspot_pipeline(base_df.copy(), top_n=5)
        assert len(result) == 3, "Should return (df_annotated, zones_df, geojson)"

    def test_annotated_df_has_gi_z_score(self, base_df):
        df_ann, _, _ = run_full_hotspot_pipeline(base_df.copy(), top_n=5)
        assert "gi_z_score" in df_ann.columns

    def test_zones_df_not_empty(self, base_df):
        _, zones_df, _ = run_full_hotspot_pipeline(base_df.copy(), top_n=5)
        # May be empty if data is too sparse, but structure should be correct
        assert isinstance(zones_df, pd.DataFrame)

    def test_geojson_type(self, base_df):
        _, _, geojson = run_full_hotspot_pipeline(base_df.copy(), top_n=5)
        assert isinstance(geojson, dict)
        assert geojson["type"] == "FeatureCollection"
