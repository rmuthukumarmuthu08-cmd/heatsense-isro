"""
test_ml_model.py — Unit tests for src/ml_model.py

Tests:
    - prepare_features: split sizes, scaling, label encoding
    - train_random_forest: R² validity, metrics keys, model type
    - train_gradient_boosting: accuracy validity, class names
    - calculate_shap_values: shape, column names
    - save_model / load_model: round-trip persistence
    - predict_heat_stress: inference on new data
    - train_full_pipeline: end-to-end
"""

import sys
import os
import json
import tempfile
import shutil
import pytest
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, GradientBoostingClassifier

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.ml_model import (
    prepare_features,
    train_random_forest,
    train_gradient_boosting,
    calculate_shap_values,
    save_model,
    load_model,
    predict_heat_stress,
    FEATURE_COLUMNS,
    HEAT_ZONE_CLASSES,
    MODEL_DIR,
)
from src.preprocessing import generate_delhi_demo_data


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────

@pytest.fixture(scope="module")
def df():
    return generate_delhi_demo_data(n_points=400, seed=42)


@pytest.fixture(scope="module")
def data_splits(df):
    return prepare_features(df, test_size=0.25)


@pytest.fixture(scope="module")
def rf_trained(data_splits):
    return train_random_forest(data_splits, n_estimators=10, max_depth=4)


@pytest.fixture(scope="module")
def gb_trained(data_splits):
    return train_gradient_boosting(data_splits, n_estimators=10, max_depth=3)


# ─────────────────────────────────────────
# prepare_features
# ─────────────────────────────────────────

class TestPrepareFeatures:

    def test_returns_dict(self, data_splits):
        assert isinstance(data_splits, dict)

    def test_required_keys(self, data_splits):
        for key in ["X_train", "X_test", "y_reg_train", "y_reg_test",
                    "y_clf_train", "y_clf_test", "feature_names",
                    "label_encoder", "scaler"]:
            assert key in data_splits, f"Missing key: {key}"

    def test_split_sizes(self, df, data_splits):
        n = len(df)
        n_train = len(data_splits["X_train"])
        n_test = len(data_splits["X_test"])
        assert n_train + n_test == n, f"Train + test ({n_train}+{n_test}) ≠ total ({n})"

    def test_test_size_approximately_correct(self, df, data_splits):
        n_test = len(data_splits["X_test"])
        expected_test = len(df) * 0.25
        assert abs(n_test - expected_test) < 5, "Test split size is wrong"

    def test_x_shape(self, data_splits):
        n_features = len(data_splits["feature_names"])
        assert data_splits["X_train"].shape[1] == n_features
        assert data_splits["X_test"].shape[1] == n_features

    def test_y_lengths_match(self, data_splits):
        assert len(data_splits["y_reg_train"]) == len(data_splits["y_clf_train"])
        assert len(data_splits["y_reg_test"]) == len(data_splits["y_clf_test"])

    def test_scaling_applied(self, data_splits):
        """Scaled X_train should have zero mean (approximately)."""
        X_sc = data_splits["X_train_scaled"]
        assert abs(X_sc.mean()) < 0.5, "Scaled features should have near-zero mean"

    def test_label_encoder_classes(self, data_splits):
        le = data_splits["label_encoder"]
        for cls in HEAT_ZONE_CLASSES:
            assert cls in le.classes_, f"Missing class in LabelEncoder: {cls}"

    def test_feature_names_subset(self, data_splits):
        for f in data_splits["feature_names"]:
            assert f in FEATURE_COLUMNS, f"Unknown feature: {f}"

    def test_no_nan_in_arrays(self, data_splits):
        for key in ["X_train", "X_test", "y_reg_train", "y_reg_test"]:
            assert not np.isnan(data_splits[key]).any(), f"NaN found in {key}"


# ─────────────────────────────────────────
# train_random_forest
# ─────────────────────────────────────────

class TestTrainRandomForest:

    def test_returns_tuple(self, rf_trained):
        assert isinstance(rf_trained, tuple) and len(rf_trained) == 2

    def test_model_type(self, rf_trained):
        rf, _ = rf_trained
        assert isinstance(rf, RandomForestRegressor)

    def test_metrics_keys(self, rf_trained):
        _, metrics = rf_trained
        for key in ["r2_test", "r2_train", "rmse_test", "mae_test",
                    "feature_importances", "y_test", "y_pred"]:
            assert key in metrics, f"Missing metric: {key}"

    def test_r2_is_float(self, rf_trained):
        _, metrics = rf_trained
        assert isinstance(metrics["r2_test"], float)

    def test_r2_reasonable(self, rf_trained):
        """R² for synthetic data should be > 0.5 even with tiny trees."""
        _, metrics = rf_trained
        assert metrics["r2_test"] > 0.3, f"R² too low: {metrics['r2_test']}"

    def test_rmse_positive(self, rf_trained):
        _, metrics = rf_trained
        assert metrics["rmse_test"] > 0

    def test_feature_importances_sum_to_one(self, rf_trained):
        _, metrics = rf_trained
        total = sum(metrics["feature_importances"].values())
        assert abs(total - 1.0) < 0.01, f"Feature importances sum to {total}"

    def test_y_pred_length(self, rf_trained, data_splits):
        _, metrics = rf_trained
        assert len(metrics["y_pred"]) == len(data_splits["y_reg_test"])

    def test_n_jobs_one(self, rf_trained):
        """n_jobs must be 1 to avoid Windows pagefile exhaustion."""
        rf, _ = rf_trained
        assert rf.n_jobs == 1, "RF must use n_jobs=1 to avoid pagefile crash"


# ─────────────────────────────────────────
# train_gradient_boosting
# ─────────────────────────────────────────

class TestTrainGradientBoosting:

    def test_returns_tuple(self, gb_trained):
        assert isinstance(gb_trained, tuple) and len(gb_trained) == 2

    def test_model_type(self, gb_trained):
        gb, _ = gb_trained
        assert isinstance(gb, GradientBoostingClassifier)

    def test_accuracy_key(self, gb_trained):
        _, metrics = gb_trained
        assert "accuracy" in metrics

    def test_accuracy_range(self, gb_trained):
        _, metrics = gb_trained
        acc = metrics["accuracy"]
        assert 0.0 <= acc <= 1.0, f"Accuracy out of range: {acc}"

    def test_class_names_correct(self, gb_trained):
        _, metrics = gb_trained
        for cls in metrics.get("class_names", []):
            assert cls in HEAT_ZONE_CLASSES, f"Unexpected class: {cls}"

    def test_confusion_matrix_shape(self, gb_trained):
        _, metrics = gb_trained
        cm = metrics.get("confusion_matrix", [])
        n = len(HEAT_ZONE_CLASSES)
        assert len(cm) == n, f"Confusion matrix should be {n}x{n}"

    def test_feature_importances_present(self, gb_trained):
        _, metrics = gb_trained
        assert "feature_importances" in metrics
        assert len(metrics["feature_importances"]) > 0


# ─────────────────────────────────────────
# calculate_shap_values
# ─────────────────────────────────────────

class TestCalculateSHAPValues:

    def test_returns_dataframe(self, rf_trained, data_splits):
        rf, _ = rf_trained
        result = calculate_shap_values(rf, data_splits["X_test"], data_splits["feature_names"])
        assert isinstance(result, pd.DataFrame)

    def test_correct_columns(self, rf_trained, data_splits):
        rf, _ = rf_trained
        result = calculate_shap_values(rf, data_splits["X_test"], data_splits["feature_names"])
        assert "feature" in result.columns
        assert "mean_abs_shap" in result.columns

    def test_row_count_matches_features(self, rf_trained, data_splits):
        rf, _ = rf_trained
        result = calculate_shap_values(rf, data_splits["X_test"], data_splits["feature_names"])
        assert len(result) == len(data_splits["feature_names"])

    def test_shap_values_non_negative(self, rf_trained, data_splits):
        rf, _ = rf_trained
        result = calculate_shap_values(rf, data_splits["X_test"], data_splits["feature_names"])
        assert (result["mean_abs_shap"] >= 0).all(), "Mean absolute SHAP values must be >= 0"

    def test_sorted_descending(self, rf_trained, data_splits):
        rf, _ = rf_trained
        result = calculate_shap_values(rf, data_splits["X_test"], data_splits["feature_names"])
        values = result["mean_abs_shap"].tolist()
        assert values == sorted(values, reverse=True), "SHAP should be sorted descending"


# ─────────────────────────────────────────
# save_model / load_model
# ─────────────────────────────────────────

class TestModelPersistence:

    def test_save_and_load(self, rf_trained, data_splits):
        rf, rf_metrics = rf_trained
        with tempfile.TemporaryDirectory() as tmpdir:
            # Temporarily override MODEL_DIR
            import src.ml_model as ml
            original_dir = ml.MODEL_DIR
            ml.MODEL_DIR = tmpdir

            try:
                path = save_model(rf, data_splits["scaler"], data_splits["label_encoder"],
                                  rf_metrics, "test_rf")
                assert os.path.exists(path), "Saved model file not found"

                bundle = load_model("test_rf")
                assert bundle is not None
                assert "model" in bundle
                assert "scaler" in bundle
                assert "metrics" in bundle
            finally:
                ml.MODEL_DIR = original_dir

    def test_load_nonexistent_returns_none(self):
        import src.ml_model as ml
        original_dir = ml.MODEL_DIR
        ml.MODEL_DIR = "/nonexistent_dir"
        try:
            result = load_model("no_such_model")
            assert result is None
        finally:
            ml.MODEL_DIR = original_dir

    def test_bundle_contains_feature_names(self, rf_trained, data_splits):
        rf, rf_metrics = rf_trained
        with tempfile.TemporaryDirectory() as tmpdir:
            import src.ml_model as ml
            original_dir = ml.MODEL_DIR
            ml.MODEL_DIR = tmpdir
            try:
                save_model(rf, data_splits["scaler"], data_splits["label_encoder"],
                           rf_metrics, "test_rf2")
                bundle = load_model("test_rf2")
                assert "feature_names" in bundle
            finally:
                ml.MODEL_DIR = original_dir


# ─────────────────────────────────────────
# predict_heat_stress
# ─────────────────────────────────────────

class TestPredictHeatStress:

    def test_adds_predicted_column(self, df, rf_trained, data_splits):
        rf, rf_metrics = rf_trained
        bundle = {
            "model": rf,
            "scaler": data_splits["scaler"],
            "label_encoder": data_splits["label_encoder"],
            "metrics": rf_metrics,
            "feature_names": data_splits["feature_names"],
        }
        result = predict_heat_stress(df.sample(50, random_state=1), bundle)
        assert "predicted_heat_stress" in result.columns

    def test_predictions_in_range(self, df, rf_trained, data_splits):
        rf, rf_metrics = rf_trained
        bundle = {
            "model": rf, "scaler": data_splits["scaler"],
            "label_encoder": data_splits["label_encoder"],
            "metrics": rf_metrics,
            "feature_names": data_splits["feature_names"],
        }
        result = predict_heat_stress(df.sample(50, random_state=2), bundle)
        preds = result["predicted_heat_stress"]
        assert preds.between(-0.1, 1.1).all(), "Predictions should be near [0, 1]"

    def test_row_count_preserved(self, df, rf_trained, data_splits):
        rf, rf_metrics = rf_trained
        bundle = {
            "model": rf, "scaler": data_splits["scaler"],
            "label_encoder": data_splits["label_encoder"],
            "metrics": rf_metrics,
            "feature_names": data_splits["feature_names"],
        }
        sample = df.sample(30, random_state=3)
        result = predict_heat_stress(sample, bundle)
        assert len(result) == 30


# ─────────────────────────────────────────
# train_full_pipeline
# ─────────────────────────────────────────

class TestTrainFullPipeline:

    @pytest.fixture(scope="class")
    def pipeline_result(self, df):
        from src.ml_model import train_full_pipeline
        import src.ml_model as ml
        # Use temp dir to avoid polluting real models/
        with tempfile.TemporaryDirectory() as tmpdir:
            original = ml.MODEL_DIR
            ml.MODEL_DIR = tmpdir
            try:
                result = train_full_pipeline(df)
            finally:
                ml.MODEL_DIR = original
        return result

    def test_returns_dict(self, pipeline_result):
        assert isinstance(pipeline_result, dict)

    def test_required_keys(self, pipeline_result):
        for k in ["rf_model", "gb_model", "rf_metrics", "gb_metrics", "shap_df", "data"]:
            assert k in pipeline_result, f"Missing key: {k}"

    def test_rf_model_fitted(self, pipeline_result):
        assert isinstance(pipeline_result["rf_model"], RandomForestRegressor)

    def test_gb_model_fitted(self, pipeline_result):
        assert isinstance(pipeline_result["gb_model"], GradientBoostingClassifier)

    def test_shap_df_valid(self, pipeline_result):
        shap_df = pipeline_result["shap_df"]
        assert isinstance(shap_df, pd.DataFrame)
        assert len(shap_df) > 0
