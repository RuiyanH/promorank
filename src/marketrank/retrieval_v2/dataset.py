"""Strict point-in-time-safe retrieval dataset construction."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import numpy as np
import torch

from marketrank.candidate_pipeline.privacy import validate_customer_identifier
from marketrank.retrieval.inference_bundle import (
    ALLOWED_CUSTOMER_INPUTS,
    FORBIDDEN_CUSTOMER_INPUTS,
)

SPLIT_BOUNDS = {
    "retrieval_fit": (dt.date(2018, 12, 19), dt.date(2020, 6, 30)),
    "retrieval_select": (dt.date(2020, 7, 1), dt.date(2020, 7, 14)),
}
RECORD_FIELDS = {
    "customer_id",
    "scoring_date",
    "positive_article_id",
    "recent_article_sequence",
    "days_since_last_purchase",
    "purchase_count_7d",
    "purchase_count_30d",
    "purchase_count_90d",
}
NUMERIC_FIELDS = (
    "days_since_last_purchase",
    "purchase_count_7d",
    "purchase_count_30d",
    "purchase_count_90d",
)


class RetrievalDatasetError(ValueError):
    """A retrieval record violates chronology or the PIT-safe input schema."""


@dataclass(frozen=True)
class RetrievalDataset:
    split: str
    customer_ids: tuple[str, ...]
    scoring_dates: tuple[str, ...]
    customer_indices: np.ndarray
    recent_article_indices: np.ndarray
    numeric_features: np.ndarray
    positive_article_indices: np.ndarray

    def __len__(self) -> int:
        return len(self.customer_ids)

    def tensors(self) -> dict[str, torch.Tensor]:
        return {
            "customer_indices": torch.from_numpy(self.customer_indices.copy()),
            "recent_article_indices": torch.from_numpy(self.recent_article_indices.copy()),
            "numeric_features": torch.from_numpy(self.numeric_features.copy()),
            "positive_article_indices": torch.from_numpy(self.positive_article_indices.copy()),
        }


def _day(value: object) -> dt.date:
    if not isinstance(value, str):
        raise RetrievalDatasetError("scoring_date must be an ISO date string")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise RetrievalDatasetError("scoring_date must be an ISO date string") from exc


def validate_retrieval_schema(fields: Iterable[str]) -> None:
    field_set = set(fields)
    forbidden = field_set & set(FORBIDDEN_CUSTOMER_INPUTS)
    if forbidden:
        raise RetrievalDatasetError(f"mutable customer fields are forbidden: {sorted(forbidden)}")
    if field_set != RECORD_FIELDS:
        raise RetrievalDatasetError(
            f"retrieval record fields mismatch; missing={sorted(RECORD_FIELDS - field_set)}, "
            f"extra={sorted(field_set - RECORD_FIELDS)}"
        )


def build_retrieval_dataset(
    records: Iterable[Mapping[str, Any]],
    *,
    split: str,
    customer_vocabulary: Mapping[str, int],
    article_vocabulary: Mapping[str, int],
    recent_k: int,
) -> RetrievalDataset:
    """Build fixed NumPy tensors from strict synthetic/opaque PIT records."""

    if split not in SPLIT_BOUNDS:
        raise RetrievalDatasetError(f"unsupported retrieval split: {split}")
    if isinstance(recent_k, bool) or not isinstance(recent_k, int) or recent_k <= 0:
        raise RetrievalDatasetError("recent_k must be a positive integer")
    rows = [dict(row) for row in records]
    if not rows:
        raise RetrievalDatasetError("retrieval dataset cannot be empty")
    lo, hi = SPLIT_BOUNDS[split]
    customers: list[str] = []
    dates: list[str] = []
    customer_indices: list[int] = []
    recent_indices: list[list[int]] = []
    numeric: list[list[float]] = []
    positive_indices: list[int] = []
    for row in rows:
        validate_retrieval_schema(row)
        customer = validate_customer_identifier(row["customer_id"])
        day = _day(row["scoring_date"])
        if not lo <= day <= hi:
            raise RetrievalDatasetError(
                f"{row['scoring_date']} is outside the frozen {split} chronology"
            )
        positive = row["positive_article_id"]
        if customer not in customer_vocabulary:
            raise RetrievalDatasetError(f"customer is absent from vocabulary: {customer}")
        if positive not in article_vocabulary or article_vocabulary[positive] <= 0:
            raise RetrievalDatasetError(f"positive article is absent from vocabulary: {positive}")
        recent = row["recent_article_sequence"]
        if not isinstance(recent, list) or len(recent) > recent_k:
            raise RetrievalDatasetError(f"recent_article_sequence must contain at most {recent_k} items")
        if any(article not in article_vocabulary for article in recent):
            raise RetrievalDatasetError("recent_article_sequence contains an unknown article")
        padded = [article_vocabulary[article] for article in recent[-recent_k:]]
        padded = [0] * (recent_k - len(padded)) + padded
        values: list[float] = []
        for field in NUMERIC_FIELDS:
            value = row[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise RetrievalDatasetError(f"{field} must be a non-negative number")
            values.append(float(value))
        customers.append(customer)
        dates.append(day.isoformat())
        customer_indices.append(int(customer_vocabulary[customer]))
        recent_indices.append(padded)
        numeric.append(values)
        positive_indices.append(int(article_vocabulary[positive]))

    return RetrievalDataset(
        split=split,
        customer_ids=tuple(customers),
        scoring_dates=tuple(dates),
        customer_indices=np.asarray(customer_indices, dtype=np.int64),
        recent_article_indices=np.asarray(recent_indices, dtype=np.int64),
        numeric_features=np.asarray(numeric, dtype=np.float32),
        positive_article_indices=np.asarray(positive_indices, dtype=np.int64),
    )


def executable_input_signature(recent_k: int) -> dict[str, Any]:
    return {
        "customer_inputs": list(ALLOWED_CUSTOMER_INPUTS),
        "tensor_inputs": {
            "customer_indices": {"dtype": "int64", "rank": 1},
            "recent_article_indices": {"dtype": "int64", "rank": 2, "width": recent_k},
            "numeric_features": {"dtype": "float32", "rank": 2, "width": len(NUMERIC_FIELDS)},
        },
        "article_inputs": ["article_id_embedding"],
        "output_dtype": "float32",
    }
