"""Exact deterministic float32 retrieval with per-day eligibility masking."""

from __future__ import annotations

import datetime as dt
from typing import Iterable, Mapping, Sequence

import numpy as np

from marketrank.candidate_pipeline.privacy import (
    CustomerIdentifierError,
    validate_customer_identifier,
)

DAY_ZERO = dt.date(2018, 9, 20)


class RetrievalError(ValueError):
    """Vectors, identifiers, or eligibility metadata are invalid."""


def _matrix(value: object, name: str) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != 2:
        raise RetrievalError(f"{name} must be a rank-2 matrix")
    if array.dtype != np.dtype(np.float32):
        raise RetrievalError(f"{name} must have dtype float32; got {array.dtype}")
    if not np.isfinite(array).all():
        raise RetrievalError(f"{name} contains a non-finite value")
    return np.ascontiguousarray(array)


def _iso_date(value: object, name: str) -> dt.date:
    if not isinstance(value, str):
        raise RetrievalError(f"{name} must be an ISO date string")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise RetrievalError(f"{name} must be an ISO date string") from exc


def exact_daily_retrieval(
    *,
    article_ids: Sequence[str],
    article_vectors: object,
    customer_ids: Sequence[str],
    customer_vectors: object,
    article_first_seen: Mapping[str, str],
    scoring_date: str,
    day_index: int,
    depth: int,
    batch_size: int = 512,
) -> list[dict[str, object]]:
    """Return exact top-k rows ordered by score then article identifier.

    The catalog matrix is accepted once and reused for any scoring date. Date
    variation is represented solely by the strict first-seen eligibility mask
    and the customer query matrix. Ranking eligible articles directly provides
    the required refill behavior when a higher-scoring future article is
    filtered.
    """

    articles = list(article_ids)
    customers = list(customer_ids)
    if len(set(articles)) != len(articles) or any(not isinstance(x, str) or not x for x in articles):
        raise RetrievalError("article_ids must be unique non-empty strings")
    if len(set(customers)) != len(customers):
        raise RetrievalError("customer_ids must be unique")
    try:
        for customer in customers:
            validate_customer_identifier(customer)
    except CustomerIdentifierError as exc:
        raise RetrievalError(str(exc)) from exc
    if isinstance(depth, bool) or not isinstance(depth, int) or depth <= 0:
        raise RetrievalError("depth must be a positive integer")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
        raise RetrievalError("batch_size must be a positive integer")
    if isinstance(day_index, bool) or not isinstance(day_index, int) or day_index < 0:
        raise RetrievalError("day_index must be a non-negative integer")

    article_matrix = _matrix(article_vectors, "article_vectors")
    query_matrix = _matrix(customer_vectors, "customer_vectors")
    if article_matrix.shape[0] != len(articles):
        raise RetrievalError("article_vectors row count does not match article_ids")
    if query_matrix.shape[0] != len(customers):
        raise RetrievalError("customer_vectors row count does not match customer_ids")
    if article_matrix.shape[1] != query_matrix.shape[1]:
        raise RetrievalError("article and customer embedding dimensions differ")
    if set(article_first_seen) != set(articles):
        missing = sorted(set(articles) - set(article_first_seen))
        extra = sorted(set(article_first_seen) - set(articles))
        raise RetrievalError(f"article first-seen coverage mismatch; missing={missing}, extra={extra}")

    score_day = _iso_date(scoring_date, "scoring_date")
    if (score_day - DAY_ZERO).days != day_index:
        raise RetrievalError("day_index does not match scoring_date relative to the dataset epoch")
    eligible_positions = [
        i
        for i, article in enumerate(articles)
        if _iso_date(article_first_seen[article], f"article_first_seen[{article}]") < score_day
    ]
    if not eligible_positions or not customers:
        return []

    eligible_matrix = np.ascontiguousarray(article_matrix[eligible_positions], dtype=np.float32)
    eligible_ids = [articles[i] for i in eligible_positions]
    limit = min(depth, len(eligible_ids))
    rows: list[dict[str, object]] = []
    for start in range(0, len(customers), batch_size):
        stop = min(start + batch_size, len(customers))
        scores = np.matmul(query_matrix[start:stop], eligible_matrix.T, dtype=np.float32)
        for local_index, score_row in enumerate(scores):
            # Partition in linear time, then sort only the winners. Include all
            # ties at the boundary so equal scores still break by article ID;
            # taking argpartition's first k directly would violate that rule.
            threshold = np.partition(score_row, len(score_row) - limit)[-limit]
            shortlist = np.flatnonzero(score_row >= threshold)
            ordered = sorted(shortlist, key=lambda i: (-float(score_row[i]), eligible_ids[i]))[:limit]
            customer_id = customers[start + local_index]
            for rank, position in enumerate(ordered, start=1):
                rows.append(
                    {
                        "customer_id": customer_id,
                        "day_index": day_index,
                        "article_id": eligible_ids[position],
                        "source": "ann",
                        "source_rank": rank,
                    }
                )
    return rows
