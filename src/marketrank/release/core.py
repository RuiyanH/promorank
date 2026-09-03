"""Pure, deterministic construction of a browser-safe workbench release."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import hmac
import json
import re
from typing import Iterable, Mapping, Sequence


REQUIRED_SOURCES = (
    "ann",
    "repurchase",
    "category_pop",
    "global_pop",
    "covisit",
)
RRF_K = 60
RRF_VERSION = "equal-weight-rrf-v1"
RANKING_MODE = "baseline_fusion"
SCHEMA_VERSION = "1.0.0"
TOP_N = 12

_ARTICLE_ID = re.compile(r"^[0-9]{10}$")
_REASON = {
    "ann": ("similar_patterns", "Similar from historical customer and article patterns"),
    "repurchase": ("previously_purchased", "Previously purchased by this historical customer"),
    "category_pop": ("preferred_category", "Popular in this historical customer's preferred category"),
    "global_pop": ("historically_popular", "Popular across the historical catalog"),
    "covisit": ("frequently_together", "Often purchased alongside recent historical choices"),
}


class ReleaseValidationError(ValueError):
    """Raised when release input violates the frozen v1 contract."""


@dataclass(frozen=True)
class CandidateRow:
    customer_id: str
    article_id: str
    source: str
    source_rank: int


@dataclass(frozen=True)
class FusedCandidate:
    article_id: str
    score: Fraction
    source_ranks: tuple[tuple[str, int], ...]


def validate_source_rows(
    sources: Mapping[str, Iterable[Mapping[str, object] | CandidateRow]],
) -> dict[str, tuple[CandidateRow, ...]]:
    """Validate and normalize the exact five-source input contract.

    A source may legitimately omit customers, but within a customer it cannot
    repeat an article or a rank. These are hard errors because either condition
    makes an RRF contribution ambiguous.
    """
    actual = set(sources)
    required = set(REQUIRED_SOURCES)
    if actual != required:
        missing = sorted(required - actual)
        extra = sorted(actual - required)
        raise ReleaseValidationError(
            f"candidate sources must be exactly {list(REQUIRED_SOURCES)}; "
            f"missing={missing}, extra={extra}"
        )

    normalized: dict[str, tuple[CandidateRow, ...]] = {}
    for source in REQUIRED_SOURCES:
        rows: list[CandidateRow] = []
        seen_articles: set[tuple[str, str]] = set()
        seen_ranks: set[tuple[str, int]] = set()
        for index, raw in enumerate(sources[source]):
            if isinstance(raw, CandidateRow):
                row = raw
            else:
                expected = {"customer_id", "article_id", "source", "source_rank"}
                if set(raw) != expected:
                    raise ReleaseValidationError(
                        f"{source}[{index}] fields must be exactly {sorted(expected)}"
                    )
                rank = raw["source_rank"]
                if isinstance(rank, bool) or not isinstance(rank, int):
                    raise ReleaseValidationError(f"{source}[{index}].source_rank must be an integer")
                row = CandidateRow(
                    customer_id=raw["customer_id"],  # type: ignore[arg-type]
                    article_id=raw["article_id"],  # type: ignore[arg-type]
                    source=raw["source"],  # type: ignore[arg-type]
                    source_rank=rank,
                )
            if not isinstance(row.customer_id, str) or not row.customer_id:
                raise ReleaseValidationError(f"{source}[{index}].customer_id must be non-empty")
            if not isinstance(row.article_id, str) or not _ARTICLE_ID.fullmatch(row.article_id):
                raise ReleaseValidationError(f"{source}[{index}].article_id must be 10 digits")
            if row.source != source:
                raise ReleaseValidationError(
                    f"{source}[{index}] is tagged {row.source!r}, expected {source!r}"
                )
            if isinstance(row.source_rank, bool) or not isinstance(row.source_rank, int) or row.source_rank < 1:
                raise ReleaseValidationError(f"{source}[{index}].source_rank must be >= 1")
            article_key = (row.customer_id, row.article_id)
            rank_key = (row.customer_id, row.source_rank)
            if article_key in seen_articles:
                raise ReleaseValidationError(
                    f"{source} repeats customer/article {article_key}"
                )
            if rank_key in seen_ranks:
                raise ReleaseValidationError(f"{source} repeats customer/rank {rank_key}")
            seen_articles.add(article_key)
            seen_ranks.add(rank_key)
            rows.append(row)
        if not rows:
            raise ReleaseValidationError(f"candidate source {source!r} is empty")
        normalized[source] = tuple(rows)
    return normalized


def reciprocal_rank_fusion(
    sources: Mapping[str, Iterable[Mapping[str, object] | CandidateRow]],
    *,
    k: int = RRF_K,
    top_n: int = TOP_N,
) -> dict[str, tuple[FusedCandidate, ...]]:
    """Apply exact equal-weight RRF, ordered by score then article ID."""
    if k != RRF_K:
        raise ReleaseValidationError(f"v1 requires k={RRF_K}")
    if top_n < 1:
        raise ReleaseValidationError("top_n must be positive")
    rows = validate_source_rows(sources)
    by_customer: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(dict))
    for source in REQUIRED_SOURCES:
        for row in rows[source]:
            by_customer[row.customer_id][row.article_id][source] = row.source_rank

    fused: dict[str, tuple[FusedCandidate, ...]] = {}
    source_position = {source: i for i, source in enumerate(REQUIRED_SOURCES)}
    for customer_id in sorted(by_customer):
        candidates: list[FusedCandidate] = []
        for article_id, ranks in by_customer[customer_id].items():
            evidence = tuple(sorted(ranks.items(), key=lambda item: source_position[item[0]]))
            score = sum((Fraction(1, k + rank) for _, rank in evidence), start=Fraction())
            candidates.append(FusedCandidate(article_id, score, evidence))
        candidates.sort(key=lambda item: (-item.score, item.article_id))
        fused[customer_id] = tuple(candidates[:top_n])
    return fused


def validate_customer_ref_key(key: bytes, *, allow_test_key: bool = False) -> bytes:
    """Validate key material without ever formatting it into an error."""
    if not isinstance(key, bytes):
        raise ReleaseValidationError("customer reference key must be bytes")
    if len(key) < 32:
        raise ReleaseValidationError("customer reference key must contain at least 32 bytes")
    normalized = key.lower().replace(b"_", b"-").replace(b" ", b"-")
    if not allow_test_key and normalized.startswith(b"test-only"):
        raise ReleaseValidationError("test-only customer reference keys cannot build real releases")
    return key


def opaque_customer_ref(
    release_id: str,
    raw_customer_id: str,
    *,
    customer_ref_key: bytes,
    allow_test_key: bool = False,
) -> str:
    """Return a deterministic HMAC identifier scoped to one release."""
    if not release_id or not raw_customer_id:
        raise ReleaseValidationError("release_id and raw_customer_id must be non-empty")
    key = validate_customer_ref_key(customer_ref_key, allow_test_key=allow_test_key)
    material = f"marketrank-workbench-v1\0{release_id}\0{raw_customer_id}".encode("utf-8")
    return "demo_" + hmac.new(key, material, hashlib.sha256).hexdigest()[:16]


def _reason(source_ranks: Sequence[tuple[str, int]]) -> dict[str, str]:
    if len(source_ranks) > 1:
        names = ", ".join(source.replace("_", " ") for source, _ in source_ranks)
        return {
            "code": "multiple_sources",
            "text": f"Supported by {len(source_ranks)} historical candidate sources: {names}",
        }
    return dict(zip(("code", "text"), _REASON[source_ranks[0][0]]))


def _validate_ceiling(ceiling: Mapping[str, object], source_row_counts: Mapping[str, int]) -> None:
    try:
        run = ceiling["run"]
        stats = ceiling["stats"]
        values = ceiling["ceiling"]
        marginal = ceiling["marginal"]
        if not all(isinstance(x, Mapping) for x in (run, stats, values, marginal)):
            raise TypeError
    except (KeyError, TypeError) as exc:
        raise ReleaseValidationError("ceiling JSON is missing run/stats/ceiling/marginal") from exc
    run = run  # type: ignore[assignment]
    stats = stats  # type: ignore[assignment]
    values = values  # type: ignore[assignment]
    marginal = marginal  # type: ignore[assignment]
    if set(run.get("sources", [])) != set(REQUIRED_SOURCES):
        raise ReleaseValidationError("ceiling JSON does not contain the exact five sources")
    for source in REQUIRED_SOURCES:
        recorded = stats.get(f"rows_from_{source}")
        if recorded != source_row_counts.get(source):
            raise ReleaseValidationError(
                f"{source} row count {source_row_counts.get(source)} != ceiling {recorded}"
            )
        if f"by_{source}" not in values:
            raise ReleaseValidationError(f"ceiling JSON is missing by_{source}")
    if marginal.get("union_ceiling") != values.get("recall_ceiling"):
        raise ReleaseValidationError("union ceiling disagrees with recall ceiling")
    if marginal.get("mean_candidates_per_customer") != stats.get("mean_candidates_per_customer"):
        raise ReleaseValidationError("mean candidate count disagrees inside ceiling JSON")


def build_release(
    *,
    release_id: str,
    candidate_sources: Mapping[str, Iterable[Mapping[str, object] | CandidateRow]],
    article_metadata: Mapping[str, Mapping[str, str]],
    ceiling: Mapping[str, object],
    source_row_counts: Mapping[str, int],
    demo_customer_ids: Sequence[str],
    customer_ref_key: bytes,
    allow_test_customer_ref_key: bool = False,
) -> dict[str, object]:
    """Build the v1 release without retaining raw customer IDs."""
    _validate_ceiling(ceiling, source_row_counts)
    fused = reciprocal_rank_fusion(candidate_sources)
    if len(demo_customer_ids) != len(set(demo_customer_ids)):
        raise ReleaseValidationError("demo_customer_ids contains duplicates")

    run = ceiling["run"]  # type: ignore[index]
    stats = ceiling["stats"]  # type: ignore[index]
    values = ceiling["ceiling"]  # type: ignore[index]
    marginal = ceiling["marginal"]  # type: ignore[index]
    source_details = marginal["sources"]  # type: ignore[index]
    customers = []
    for display_index, raw_customer_id in enumerate(demo_customer_ids, start=1):
        recommendations = fused.get(raw_customer_id)
        if recommendations is None or len(recommendations) != TOP_N:
            raise ReleaseValidationError(
                f"demo customer {display_index} does not have {TOP_N} unique candidates"
            )
        rendered = []
        for position, item in enumerate(recommendations, start=1):
            metadata = article_metadata.get(item.article_id)
            if metadata is None:
                raise ReleaseValidationError(f"article metadata is missing {item.article_id}")
            allowed = (
                "product_name",
                "product_type_name",
                "colour_group_name",
                "department_name",
                "index_group_name",
                "garment_group_name",
            )
            if set(metadata) != set(allowed) or any(not isinstance(metadata[key], str) for key in allowed):
                raise ReleaseValidationError(
                    f"article metadata for {item.article_id} must contain exactly {list(allowed)}"
                )
            rendered.append(
                {
                    "position": position,
                    "article_id": item.article_id,
                    "metadata": {key: metadata[key] for key in allowed},
                    "fusion_score": float(item.score),
                    "source_evidence": [
                        {"source": source, "source_rank": rank}
                        for source, rank in item.source_ranks
                    ],
                    "reason": _reason(item.source_ranks),
                }
            )
        customers.append(
            {
                "customer_ref": opaque_customer_ref(
                    release_id,
                    raw_customer_id,
                    customer_ref_key=customer_ref_key,
                    allow_test_key=allow_test_customer_ref_key,
                ),
                "display_label": f"Demo customer {display_index:02d}",
                "recommendations": rendered,
            }
        )
    refs = [customer["customer_ref"] for customer in customers]
    if len(refs) != len(set(refs)):
        raise ReleaseValidationError("opaque customer reference collision")

    source_metrics = []
    for source in REQUIRED_SOURCES:
        detail = source_details[source]
        source_metrics.append(
            {
                "source": source,
                "candidate_rows": source_row_counts[source],
                "solo_recall_ceiling": values[f"by_{source}"],
                "reach_customers": detail["reach_customers"],
                "reach_fraction": detail["reach_frac"],
            }
        )

    release = {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "release_id": release_id,
            "as_of": run["as_of"],
            "slice": run["slice"],
            "ranking_mode": RANKING_MODE,
            "ranking_version": RRF_VERSION,
            "warning": "Candidate-only baseline with no trained ranker; historical data, not live recommendations.",
            "provenance_status": "backfilled",
            "demo_customer_count": len(customers),
            "cohort_customer_count": stats["n_customers"],
            "rrf": {
                "k": RRF_K,
                "source_weights": {source: 1.0 for source in REQUIRED_SOURCES},
            },
        },
        "diagnostics": {
            "candidate_recall_ceiling": values["recall_ceiling"],
            "mean_candidate_count": stats["mean_candidates_per_customer"],
            "union_candidate_rows": stats["n_candidate_rows"],
            "source_metrics": source_metrics,
            "definitions": {
                "candidate_recall_ceiling": "Share of held-out purchased customer/article pairs found anywhere in the full candidate union.",
                "mean_candidate_count": "Mean number of unique union candidates per customer in the full metric cohort.",
                "source_recall_ceiling": "Share of held-out purchased pairs found by one candidate source before fusion.",
                "fusion_score": "Ordering-only reciprocal-rank-fusion value; it is not a probability or confidence.",
            },
            "scope": "Full historical val_tune cohort on 2020-08-12; source diagnostics cover 20,000 customers, while the browser exposes only a compact deterministic sample. Article labels are current-state snapshot attributes, not point-in-time history.",
        },
        "customers": customers,
    }
    serialized = dumps_release(release)
    for raw_customer_id in demo_customer_ids:
        if raw_customer_id in serialized:
            raise ReleaseValidationError("raw customer ID entered serialized release")
    return release


def dumps_release(release: Mapping[str, object]) -> str:
    """Canonical, byte-stable JSON representation."""
    return json.dumps(release, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
