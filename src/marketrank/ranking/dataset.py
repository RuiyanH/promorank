"""Frozen primary feature and sampling contract for V2."""
from __future__ import annotations

import hashlib
import math
from datetime import date

import numpy as np
import pyarrow as pa

SOURCES = ("repurchase", "category_pop", "global_pop", "covisit", "ann")
SEED = 20260903
NEGATIVE_RETENTION = 0.05
FEATURES = (
    *(f"{source}_rank" for source in SOURCES), "source_count",
    "purchase_count_7d", "purchase_count_30d", "purchase_count_90d",
    "days_since_last_purchase", "article_count_7d", "article_count_30d",
    "article_trailing_price", "article_trailing_price_missing",
    "customer_trailing_price", "customer_trailing_price_missing",
    "price_ratio", "product_type_no", "customer_category_count_90d",
    "customer_article_count_90d", "customer_article_recency",
)
BOUNDS = {
    "ranker_fit": ("2020-07-15", "2020-08-11"),
    "val_tune": ("2020-08-12", "2020-08-25"),
    "val_calib": ("2020-08-26", "2020-09-01"),
    "test": ("2020-09-09", "2020-09-15"),
    "holdout": ("2020-09-16", "2020-09-22"),
}


def validate_split_dates(split: str, days: list[str]) -> None:
    if split not in BOUNDS or not days:
        raise ValueError("a supported nonempty ranking split is required")
    lo, hi = map(date.fromisoformat, BOUNDS[split])
    if any(not lo <= date.fromisoformat(day) <= hi for day in days):
        raise ValueError("scoring date violates ranking split chronology")


def keep_negative(customer: str, day: str, article: str, q: float = NEGATIVE_RETENTION) -> bool:
    if not math.isfinite(q) or not 0 < q <= 1:
        raise ValueError("negative retention must be in (0, 1]")
    digest = hashlib.sha256(f"{SEED}\0{customer}\0{day}\0{article}".encode()).hexdigest()
    return int(digest[:15], 16) < int(q * 16**15)


def validate_frame_manifest(manifest: dict, split: str) -> None:
    if manifest.get("schema_version") != "ranker-frame.v2" or manifest.get("spine_type") != "active_day":
        raise ValueError("ranker requires a V2 active_day frame")
    if manifest.get("split") != split or manifest.get("features") != list(FEATURES):
        raise ValueError("frame split/features differ from the frozen contract")
    validate_split_dates(split, manifest["dates"])
    q = manifest.get("negative_retention_probability")
    if q != (NEGATIVE_RETENTION if split == "ranker_fit" else 1.0):
        raise ValueError("training uses constant q=0.05; later splits must be unsampled")


def feature_matrix(table: pa.Table) -> np.ndarray:
    missing = set(FEATURES) - set(table.column_names)
    if missing:
        raise ValueError(f"missing primary features: {sorted(missing)}")
    matrix = np.column_stack([
        table[name].cast(pa.float32()).to_numpy(zero_copy_only=False) for name in FEATURES
    ])
    if np.isinf(matrix).any():
        raise ValueError("infinite features are invalid")
    return matrix.astype(np.float32, copy=False)


def prior_odds_correction(sampled_probability, q: float = NEGATIVE_RETENTION):
    """Apply q*p/(1-p+q*p) once; never apply to already corrected scores."""
    p = np.asarray(sampled_probability, dtype=np.float64)
    if not 0 < q <= 1 or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("invalid probability or negative sampling rate")
    return q * p / (1 - p + q * p)


def rrf_scores(table: pa.Table) -> np.ndarray:
    scores = np.zeros(len(table), dtype=np.float64)
    for source in SOURCES:
        ranks = table[f"{source}_rank"].cast(pa.float64()).to_numpy(zero_copy_only=False)
        valid = np.isfinite(ranks) & (ranks > 0)
        scores[valid] += 1 / (60 + ranks[valid])
    return scores
