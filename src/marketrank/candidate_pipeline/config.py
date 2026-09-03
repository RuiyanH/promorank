"""Strict loader for the frozen V2 five-source candidate configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "candidate-config.v2"
EXPECTED_CONFIG_ID = "v2-five-source-30-40-40-40-50"
SOURCE_ORDER = ("repurchase", "category_pop", "global_pop", "covisit", "ann")
SPINE_TYPES = ("active_day", "replay_day")


class CandidateConfigError(ValueError):
    """The candidate configuration does not match the frozen V2 contract."""


def _exact_keys(value: Mapping[str, Any], expected: set[str], where: str) -> None:
    got = set(value)
    if got != expected:
        missing = sorted(expected - got)
        extra = sorted(got - expected)
        raise CandidateConfigError(f"{where} keys mismatch; missing={missing}, extra={extra}")


def _positive_int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CandidateConfigError(f"{where} must be a positive integer")
    return value


@dataclass(frozen=True)
class CandidateConfig:
    """Validated immutable view of ``candidate-config.v2``."""

    _raw_json: str

    @property
    def raw(self) -> dict[str, Any]:
        """Return a detached copy so callers cannot mutate the frozen contract."""

        return json.loads(self._raw_json)

    @property
    def candidate_config_id(self) -> str:
        return str(self.raw["candidate_config_id"])

    @property
    def warm_up_days(self) -> int:
        return int(self.raw["warm_up_days"])

    @property
    def source_names(self) -> tuple[str, ...]:
        return SOURCE_ORDER

    def depth(self, source: str) -> int:
        if source not in SOURCE_ORDER:
            raise CandidateConfigError(f"unknown candidate source: {source}")
        return int(self.raw["sources"][source]["depth"])

    @property
    def recent_k(self) -> int:
        """Frozen number of recent items used to seed co-visitation."""

        return int(self.raw["sources"]["covisit"]["recent_k"])

    def as_dict(self) -> dict[str, Any]:
        return self.raw


def validate_candidate_config(value: Mapping[str, Any]) -> CandidateConfig:
    if not isinstance(value, Mapping):
        raise CandidateConfigError("candidate configuration must be a JSON object")
    _exact_keys(
        value,
        {
            "schema_version",
            "candidate_config_id",
            "spine_types",
            "warm_up_days",
            "article_eligibility",
            "sources",
            "rrf_comparator",
        },
        "candidate config",
    )
    if value["schema_version"] != SCHEMA_VERSION:
        raise CandidateConfigError(f"schema_version must be {SCHEMA_VERSION}")
    if value["candidate_config_id"] != EXPECTED_CONFIG_ID:
        raise CandidateConfigError(f"candidate_config_id must be {EXPECTED_CONFIG_ID}")
    if value["spine_types"] != list(SPINE_TYPES):
        raise CandidateConfigError(f"spine_types must be {list(SPINE_TYPES)} in order")
    if _positive_int(value["warm_up_days"], "warm_up_days") != 90:
        raise CandidateConfigError("warm_up_days must be 90")
    if value["article_eligibility"] != "first_observed_transaction_date_lt_scoring_date":
        raise CandidateConfigError("article_eligibility is not the frozen strict-before-day rule")

    sources = value["sources"]
    if not isinstance(sources, Mapping):
        raise CandidateConfigError("sources must be an object")
    _exact_keys(sources, set(SOURCE_ORDER), "sources")
    expected_depths = {
        "repurchase": 30,
        "category_pop": 40,
        "global_pop": 40,
        "covisit": 40,
        "ann": 50,
    }
    for source in SOURCE_ORDER:
        spec = sources[source]
        if not isinstance(spec, Mapping):
            raise CandidateConfigError(f"sources.{source} must be an object")
        expected_keys = {"depth"}
        if source == "covisit":
            expected_keys |= {"lookback_days", "max_basket", "cadence_days", "recent_k"}
        elif source == "ann":
            expected_keys |= {"display_name", "algorithm", "dtype", "tie_break", "bundle_contract"}
        _exact_keys(spec, expected_keys, f"sources.{source}")
        if _positive_int(spec["depth"], f"sources.{source}.depth") != expected_depths[source]:
            raise CandidateConfigError(
                f"sources.{source}.depth must be {expected_depths[source]} for {EXPECTED_CONFIG_ID}"
            )
    covisit = sources["covisit"]
    if (
        covisit["lookback_days"],
        covisit["max_basket"],
        covisit["cadence_days"],
        covisit["recent_k"],
    ) != (30, 20, 7, 10):
        raise CandidateConfigError(
            "covisit parameters must be lookback=30, max_basket=20, cadence=7, recent_k=10"
        )
    ann = sources["ann"]
    expected_ann = {
        "display_name": "embedding_retrieval",
        "algorithm": "exact_batched_inner_product",
        "dtype": "float32",
        "tie_break": "article_id_ascending",
        "bundle_contract": "inference-bundle.json",
    }
    for key, expected in expected_ann.items():
        if ann[key] != expected:
            raise CandidateConfigError(f"sources.ann.{key} must be {expected!r}")

    rrf = value["rrf_comparator"]
    if not isinstance(rrf, Mapping):
        raise CandidateConfigError("rrf_comparator must be an object")
    _exact_keys(
        rrf,
        {"k", "weights", "missing_source_contribution", "duplicate_merge", "ordering"},
        "rrf_comparator",
    )
    if rrf["k"] != 60 or rrf["missing_source_contribution"] != 0:
        raise CandidateConfigError("RRF must use k=60 and zero missing-source contribution")
    if rrf["weights"] != {name: 1 for name in SOURCE_ORDER}:
        raise CandidateConfigError("RRF must assign weight 1 to exactly the five frozen sources")
    if rrf["duplicate_merge"] != "one_rank_per_named_source":
        raise CandidateConfigError("RRF duplicate merge rule is not frozen")
    if rrf["ordering"] != ["score_descending", "article_id_ascending"]:
        raise CandidateConfigError("RRF ordering is not frozen")
    return CandidateConfig(json.dumps(value, sort_keys=True, separators=(",", ":")))


def load_candidate_config(path_or_value: str | Path | Mapping[str, Any]) -> CandidateConfig:
    """Read and validate the exact, versioned V2 candidate configuration."""

    if isinstance(path_or_value, Mapping):
        return validate_candidate_config(path_or_value)
    path = Path(path_or_value)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateConfigError(f"cannot read candidate config {path}: {exc}") from exc
    return validate_candidate_config(value)
