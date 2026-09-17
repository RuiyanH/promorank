"""Frozen LightGBM selection, offline calibration, and immutable model loading."""
from __future__ import annotations

import itertools
import importlib.metadata
import json
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pyarrow as pa
from sklearn.isotonic import IsotonicRegression

from marketrank.evidence import sha256, write_json
from .dataset import FEATURES, NEGATIVE_RETENTION, SEED, feature_matrix, prior_odds_correction, rrf_scores
from .metrics import evaluate


def configurations() -> list[dict]:
    return [{"configuration_id": f"leaves{leaves}_lr{rate}_min{minimum}",
             "num_leaves": leaves, "learning_rate": rate, "min_data_in_leaf": minimum}
            for leaves, rate, minimum in itertools.product((31, 63), (.03, .05), (200, 1000))]


def train_ranker(fit: pa.Table, tune: pa.Table, groups: pa.Table, output: Path,
                 *, threads: int = 4, grid: list[dict] | None = None,
                 rounds: int = 2000, stopping_rounds: int = 100) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("model output must be absent or empty")
    if len(fit) == 0 or len(tune) == 0:
        raise ValueError("fit and tune data must be nonempty")
    fit_labels = np.asarray(fit["label"], dtype=np.int32)
    tune_labels = np.asarray(tune["label"], dtype=np.int32)
    if set(np.unique(fit_labels)) != {0, 1} or set(np.unique(tune_labels)) != {0, 1}:
        raise ValueError("fit and tune must both contain positive and negative labels")
    x_train, x_tune = feature_matrix(fit), feature_matrix(tune)
    train_set = lgb.Dataset(x_train, label=fit_labels, feature_name=list(FEATURES), free_raw_data=False)
    val_set = lgb.Dataset(x_tune, label=tune_labels, reference=train_set, free_raw_data=False)
    results = []
    output.mkdir(parents=True, exist_ok=True)
    for configuration in grid if grid is not None else configurations():
        params = {
            "objective": "binary", "metric": "binary_logloss", "verbosity": -1,
            "deterministic": True, "force_col_wise": True,
            "seed": SEED, "feature_fraction_seed": SEED, "bagging_seed": SEED,
            "data_random_seed": SEED, "drop_seed": SEED,
            "feature_fraction": .9, "bagging_fraction": 1., "max_depth": -1,
            "num_threads": threads, "feature_pre_filter": False,
            **{key: value for key, value in configuration.items() if key != "configuration_id"},
        }
        model = lgb.train(params, train_set, num_boost_round=rounds, valid_sets=[val_set],
                          callbacks=[lgb.early_stopping(stopping_rounds, verbose=False)])
        scores = model.predict(x_tune, raw_score=True, num_threads=threads)
        report, _ = evaluate(tune, scores, groups)
        path = output / f"{configuration['configuration_id']}.txt"
        model.save_model(str(path))
        result = {**configuration, "best_iteration": model.best_iteration, "metrics": report,
                  "model_file": path.name, "sha256": sha256(path)}
        results.append(result)
        write_json(output / "selection-progress.json", {"completed": results, "split": "val_tune"})
    if not results:
        raise ValueError("model selection requires at least one configuration")
    selected = sorted(results, key=lambda result: (
        -result["metrics"]["active_day_end_to_end_ndcg_at_12"],
        -result["metrics"]["active_day_candidate_conditional_ndcg_at_12"],
        result["num_leaves"], result["configuration_id"],
    ))[0]
    baseline, _ = evaluate(tune, rrf_scores(tune), groups)
    manifest = {
        "schema_version": "ranker-model.v2", "features": list(FEATURES),
        "fit_split": "ranker_fit", "selection_split": "val_tune", "spine_type": "active_day",
        "model_available_after": "2020-08-25", "ordering_score": "raw_binary_margin",
        "negative_retention_probability": NEGATIVE_RETENTION, "sample_weights": False,
        "seed": SEED, "lightgbm_version": lgb.__version__, "selected": selected,
        "configurations": results, "rrf_val_tune": baseline,
        "fit_rows": len(fit), "tune_rows": len(tune), "frozen": True,
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def load_model(root: Path) -> tuple[lgb.Booster, dict]:
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("schema_version") != "ranker-model.v2" or manifest.get("features") != list(FEATURES):
        raise ValueError("ranker model contract mismatch")
    path = (root / manifest["selected"]["model_file"]).resolve()
    if path.parent != root.resolve() or sha256(path) != manifest["selected"]["sha256"]:
        raise ValueError("ranker checksum/path mismatch")
    return lgb.Booster(model_file=str(path)), manifest


def calibration_diagnostics(labels, probabilities) -> dict:
    y, p = np.asarray(labels, dtype=float), np.asarray(probabilities, dtype=float)
    if len(y) != len(p) or len(y) < 3000 or y.sum() < 500 or not np.isin(y, [0, 1]).all():
        raise ValueError("calibration diagnostics require >=3000 rows and >=500 positive labels")
    if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("calibration probabilities must be finite in [0,1]")
    p = np.clip(p, 1e-7, 1 - 1e-7)
    bins, ece = [], 0.
    for positions in np.array_split(np.argsort(p, kind="stable"), 15):
        if len(positions) < 200:
            raise ValueError("calibration bins require at least 200 rows")
        predicted, observed = float(p[positions].mean()), float(y[positions].mean())
        ece += len(positions) / len(y) * abs(predicted - observed)
        bins.append({"rows": len(positions), "predicted": predicted, "observed": observed})
    return {"rows": len(y), "positives": int(y.sum()), "ece_15_equal_frequency": ece,
            "brier": float(np.mean((p - y) ** 2)),
            "log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log1p(-p))),
            "bins": bins, "conditioning": "observed_active_customer_day_and_candidate_inclusion"}


def fit_calibrator(model_root: Path, table: pa.Table, output: Path, *, threads: int = 4) -> dict:
    if output.exists():
        raise ValueError("calibration output must not already exist")
    model, manifest = load_model(model_root)
    sampled = model.predict(feature_matrix(table), num_threads=threads)
    corrected = prior_odds_correction(sampled, manifest["negative_retention_probability"])
    labels = np.asarray(table["label"], dtype=np.int32)
    before = calibration_diagnostics(labels, corrected)
    calibrator = IsotonicRegression(out_of_bounds="clip").fit(corrected, labels)
    output.mkdir(parents=True)
    joblib.dump(calibrator, output / "calibrator.joblib")
    result = {"schema_version": "calibration.v2", "fit_split": "val_calib",
              "scikit_learn_version":importlib.metadata.version("scikit-learn"),"joblib_version":joblib.__version__,
              "calibrator_available_after": "2020-09-01", "odds_correction_count": 1,
              "negative_retention_probability": NEGATIVE_RETENTION,
              "model_manifest_sha256": sha256(model_root / "manifest.json"),
              "calibrator_sha256": sha256(output / "calibrator.joblib"),
              "out_of_bounds": "clip", "before": before,
              "after_fit_diagnostic": calibration_diagnostics(labels, calibrator.predict(corrected)),
              "interpretation": "offline diagnostic only; fit-slice calibration is not held-out evidence"}
    write_json(output / "manifest.json", result)
    return result
