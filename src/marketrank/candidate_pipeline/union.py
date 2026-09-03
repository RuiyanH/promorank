"""Deterministic five-source candidate union for synthetic A0 validation."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any, Iterable, Mapping

from .config import CandidateConfig, SOURCE_ORDER
from .privacy import CustomerIdentifierError, validate_customer_identifier

REQUIRED_SOURCES = SOURCE_ORDER
SPINE_TYPES = frozenset({"active_day", "replay_day"})


class CandidateUnionError(ValueError):
    """Candidate source or spine input violates the frozen V2 contract."""


def daily_ann_to_candidate_source(partition: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt a validated daily-ANN reader result to the union source contract."""

    if not {"manifest", "rows"}.issubset(partition):
        raise CandidateUnionError("daily ANN reader result requires manifest and rows")
    manifest = partition["manifest"]
    rows = partition["rows"]
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != "daily-ann.v2":
        raise CandidateUnionError("daily ANN manifest schema mismatch")
    if manifest.get("source") != "ann":
        raise CandidateUnionError("daily ANN manifest source must be ann")
    return {
        "schema_version": "candidate-source.v2",
        "source": "ann",
        "scoring_date": manifest["scoring_date"],
        "spine_type": manifest["spine_type"],
        "candidate_config_id": manifest["candidate_config_id"],
        "rows": [
            {
                "customer_key": row["customer_id"],
                "article_id": row["article_id"],
                "source_rank": row["source_rank"],
            }
            for row in rows
        ],
    }


def _date(value: object, where: str) -> dt.date:
    if not isinstance(value, str):
        raise CandidateUnionError(f"{where} must be an ISO date string")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise CandidateUnionError(f"{where} must be an ISO date string") from exc


def validate_spine_type(rows: Iterable[Mapping[str, Any]], expected: str | None = None) -> str:
    """Require one recognized spine type across all supplied rows."""

    values = {row.get("spine_type") for row in rows}
    if not values:
        if expected not in SPINE_TYPES:
            raise CandidateUnionError("empty spine rows require an explicit valid spine_type")
        return expected
    if len(values) != 1:
        raise CandidateUnionError(f"mixed spine_type values are forbidden: {sorted(map(str, values))}")
    value = next(iter(values))
    if value not in SPINE_TYPES:
        raise CandidateUnionError(f"invalid spine_type: {value!r}")
    if expected is not None and value != expected:
        raise CandidateUnionError(f"spine_type {value!r} does not match expected {expected!r}")
    return str(value)


def _validate_source_artifact(
    source: str,
    artifact: Mapping[str, Any],
    *,
    scoring_date: str,
    spine_type: str,
    config: CandidateConfig,
) -> list[Mapping[str, Any]]:
    required = {"schema_version", "source", "scoring_date", "spine_type", "candidate_config_id", "rows"}
    missing = sorted(required - set(artifact))
    extra = sorted(set(artifact) - required)
    if missing or extra:
        raise CandidateUnionError(
            f"{source} artifact keys mismatch; missing={missing}, extra={extra}"
        )
    if artifact["schema_version"] != "candidate-source.v2":
        raise CandidateUnionError(f"{source} artifact has invalid schema_version")
    if artifact["source"] != source:
        raise CandidateUnionError(f"{source} artifact declares source {artifact['source']!r}")
    if artifact["scoring_date"] != scoring_date:
        raise CandidateUnionError(f"{source} artifact date does not match {scoring_date}")
    if artifact["spine_type"] != spine_type:
        raise CandidateUnionError(f"{source} artifact spine_type does not match {spine_type}")
    if artifact["candidate_config_id"] != config.candidate_config_id:
        raise CandidateUnionError(f"{source} artifact candidate_config_id mismatch")
    rows = artifact["rows"]
    if not isinstance(rows, list):
        raise CandidateUnionError(f"{source} artifact rows must be a list")
    return rows


def union_candidate_sources(
    *,
    scoring_date: str,
    spine_type: str,
    groups: Iterable[Mapping[str, Any]],
    source_artifacts: Mapping[str, Mapping[str, Any]],
    config: CandidateConfig,
    article_first_seen: Mapping[str, str],
    bundle_id: str,
) -> dict[str, Any]:
    """Union one date's five source artifacts while preserving all evidence.

    A source artifact is mandatory even when it has zero rows. A particular
    customer may be absent from any source. Truth is carried only for synthetic
    reachability tests; it never affects candidate membership.
    """

    score_day = _date(scoring_date, "scoring_date")
    if not isinstance(bundle_id, str) or not bundle_id:
        raise CandidateUnionError("bundle_id must be a non-empty string")
    if spine_type not in SPINE_TYPES:
        raise CandidateUnionError(f"invalid spine_type: {spine_type!r}")
    missing_sources = sorted(set(REQUIRED_SOURCES) - set(source_artifacts))
    extra_sources = sorted(set(source_artifacts) - set(REQUIRED_SOURCES))
    if missing_sources or extra_sources:
        raise CandidateUnionError(
            f"date-level sources mismatch; missing={missing_sources}, extra={extra_sources}"
        )

    group_list = [dict(group) for group in groups]
    validate_spine_type(group_list, spine_type)
    group_by_customer: dict[str, dict[str, Any]] = {}
    for group in group_list:
        required = {"customer_key", "scoring_date", "spine_type"}
        if not required.issubset(group):
            raise CandidateUnionError(f"spine group is missing {sorted(required - set(group))}")
        customer = group["customer_key"]
        try:
            validate_customer_identifier(customer)
        except CustomerIdentifierError as exc:
            raise CandidateUnionError(str(exc)) from exc
        if customer in group_by_customer:
            raise CandidateUnionError(f"duplicate spine group for {customer}")
        if group["scoring_date"] != scoring_date:
            raise CandidateUnionError("spine group scoring_date mismatch")
        truth = group.get("truth_articles", [])
        if spine_type == "replay_day" and truth:
            raise CandidateUnionError("replay_day groups cannot carry outcome labels")
        if not isinstance(truth, list) or any(not isinstance(x, str) for x in truth):
            raise CandidateUnionError("truth_articles must be a list of strings")
        group_by_customer[customer] = {
            "customer_key": customer,
            "scoring_date": scoring_date,
            "spine_type": spine_type,
            "truth_articles": list(truth),
        }

    evidence: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    for source in REQUIRED_SOURCES:
        rows = _validate_source_artifact(
            source,
            source_artifacts[source],
            scoring_date=scoring_date,
            spine_type=spine_type,
            config=config,
        )
        seen_ranks: dict[str, set[int]] = defaultdict(set)
        seen_articles: set[tuple[str, str]] = set()
        for row in rows:
            if set(row) != {"customer_key", "article_id", "source_rank"}:
                raise CandidateUnionError(f"{source} source row has unexpected fields")
            customer = row["customer_key"]
            article = row["article_id"]
            rank = row["source_rank"]
            if customer not in group_by_customer:
                raise CandidateUnionError(f"{source} row references a customer outside the spine")
            if not isinstance(article, str) or not article:
                raise CandidateUnionError(f"{source} article_id must be a non-empty string")
            if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= config.depth(source):
                raise CandidateUnionError(f"{source} source_rank is outside its configured depth")
            if rank in seen_ranks[customer]:
                raise CandidateUnionError(f"{source} has duplicate rank {rank} for {customer}")
            if (customer, article) in seen_articles:
                raise CandidateUnionError(f"{source} repeats article {article} for {customer}")
            if article not in article_first_seen:
                raise CandidateUnionError(f"{source} article {article} lacks first-seen provenance")
            if _date(article_first_seen[article], f"first_seen[{article}]") >= score_day:
                raise CandidateUnionError(f"{source} emitted ineligible article {article} on {scoring_date}")
            seen_ranks[customer].add(rank)
            seen_articles.add((customer, article))
            evidence[(customer, article)][source] = rank
        for customer, ranks in seen_ranks.items():
            ordered = sorted(ranks)
            if ordered != list(range(1, len(ordered) + 1)):
                raise CandidateUnionError(
                    f"{source} ranks for {customer} are not contiguous from 1"
                )

    output_groups = []
    for customer in sorted(group_by_customer):
        group = group_by_customer[customer]
        candidates = []
        articles = sorted(article for cust, article in evidence if cust == customer)
        for article in articles:
            ranks = evidence[(customer, article)]
            row: dict[str, Any] = {"article_id": article}
            for source in REQUIRED_SOURCES:
                rank = ranks.get(source)
                row[f"{source}_rank"] = rank
                row[f"from_{source}"] = rank is not None
            row["source_count"] = len(ranks)
            candidates.append(row)
        group["candidates"] = candidates
        output_groups.append(group)

    return {
        "schema_version": "candidate-set.v2",
        "candidate_config_id": config.candidate_config_id,
        "bundle_id": bundle_id,
        "date_manifest": {
            "scoring_date": scoring_date,
            "spine_type": spine_type,
            "source_artifacts": list(REQUIRED_SOURCES),
            "eligible_article_count": sum(
                1 for first_seen in article_first_seen.values() if _date(first_seen, "first_seen") < score_day
            ),
        },
        "groups": output_groups,
    }
