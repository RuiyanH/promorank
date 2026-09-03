from __future__ import annotations

from pathlib import Path

import pytest

from marketrank.candidate_pipeline.config import load_candidate_config
from marketrank.candidate_pipeline.union import (
    CandidateUnionError,
    REQUIRED_SOURCES,
    daily_ann_to_candidate_source,
    union_candidate_sources,
)
from marketrank.retrieval.daily_ann import read_daily_ann_partition, write_daily_ann_partition

CONFIG = load_candidate_config(Path("tests/fixtures/contracts_v2/candidate-config.json"))
FIRST_SEEN = {"a1": "2020-01-01", "a2": "2020-01-02", "future": "2020-07-15"}
INPUT_HASHES = {"catalog": "1" * 64, "queries": "2" * 64, "article_first_seen": "3" * 64}
BUNDLE_ID = "v2_pit_safe_synthetic_fixture"


def _groups(spine="active_day"):
    return [
        {"customer_key": "synthetic_c1", "scoring_date": "2020-07-15", "spine_type": spine,
         "truth_articles": ["future"] if spine == "active_day" else []},
        {"customer_key": "synthetic_c2", "scoring_date": "2020-07-15", "spine_type": spine,
         "truth_articles": []},
    ]


def _sources(spine="active_day"):
    artifacts = {}
    for source in REQUIRED_SOURCES:
        rows = []
        if source == "repurchase":
            rows = [{"customer_key": "synthetic_c1", "article_id": "a1", "source_rank": 1}]
        elif source == "global_pop":
            rows = [
                {"customer_key": "synthetic_c1", "article_id": "a1", "source_rank": 1},
                {"customer_key": "synthetic_c2", "article_id": "a2", "source_rank": 1},
            ]
        elif source == "ann":
            rows = [{"customer_key": "synthetic_c1", "article_id": "a2", "source_rank": 1}]
        artifacts[source] = {
            "schema_version": "candidate-source.v2", "source": source,
            "scoring_date": "2020-07-15", "spine_type": spine,
            "candidate_config_id": CONFIG.candidate_config_id, "rows": rows,
        }
    return artifacts


def test_union_retains_flags_ranks_and_unreachable_positive():
    result = union_candidate_sources(
        scoring_date="2020-07-15", spine_type="active_day", groups=_groups(),
        source_artifacts=_sources(), config=CONFIG, article_first_seen=FIRST_SEEN,
        bundle_id=BUNDLE_ID,
    )
    c1 = result["groups"][0]
    assert c1["truth_articles"] == ["future"]
    assert all(row["article_id"] != "future" for row in c1["candidates"])
    a1 = next(row for row in c1["candidates"] if row["article_id"] == "a1")
    assert a1["repurchase_rank"] == 1 and a1["from_repurchase"] is True
    assert a1["global_pop_rank"] == 1 and a1["source_count"] == 2
    assert a1["ann_rank"] is None and a1["from_ann"] is False


def test_customer_can_lack_source_membership_while_date_has_all_sources():
    result = union_candidate_sources(
        scoring_date="2020-07-15", spine_type="active_day", groups=_groups(),
        source_artifacts=_sources(), config=CONFIG, article_first_seen=FIRST_SEEN,
        bundle_id=BUNDLE_ID,
    )
    c2 = result["groups"][1]
    assert len(c2["candidates"]) == 1
    assert c2["candidates"][0]["ann_rank"] is None
    assert result["date_manifest"]["source_artifacts"] == list(REQUIRED_SOURCES)


def test_missing_date_level_source_fails():
    sources = _sources()
    sources.pop("covisit")
    with pytest.raises(CandidateUnionError, match="date-level sources mismatch"):
        union_candidate_sources(
            scoring_date="2020-07-15", spine_type="active_day", groups=_groups(),
            source_artifacts=sources, config=CONFIG, article_first_seen=FIRST_SEEN,
            bundle_id=BUNDLE_ID,
        )


def test_mixed_spines_fail():
    groups = _groups()
    groups[1]["spine_type"] = "replay_day"
    with pytest.raises(CandidateUnionError, match="mixed spine_type"):
        union_candidate_sources(
            scoring_date="2020-07-15", spine_type="active_day", groups=groups,
            source_artifacts=_sources(), config=CONFIG, article_first_seen=FIRST_SEEN,
            bundle_id=BUNDLE_ID,
        )


def test_replay_spine_rejects_outcome_labels():
    groups = _groups("replay_day")
    groups[0]["truth_articles"] = ["a1"]
    with pytest.raises(CandidateUnionError, match="cannot carry outcome"):
        union_candidate_sources(
            scoring_date="2020-07-15", spine_type="replay_day", groups=groups,
            source_artifacts=_sources("replay_day"), config=CONFIG,
            article_first_seen=FIRST_SEEN, bundle_id=BUNDLE_ID,
        )


def test_replay_spine_succeeds_without_outcome_labels():
    result = union_candidate_sources(
        scoring_date="2020-07-15", spine_type="replay_day", groups=_groups("replay_day"),
        source_artifacts=_sources("replay_day"), config=CONFIG,
        article_first_seen=FIRST_SEEN, bundle_id=BUNDLE_ID,
    )
    assert {group["spine_type"] for group in result["groups"]} == {"replay_day"}


def test_source_ranks_must_be_contiguous_after_filter_refill():
    sources = _sources()
    sources["ann"]["rows"][0]["source_rank"] = 2
    with pytest.raises(CandidateUnionError, match="contiguous"):
        union_candidate_sources(
            scoring_date="2020-07-15", spine_type="active_day", groups=_groups(),
            source_artifacts=sources, config=CONFIG, article_first_seen=FIRST_SEEN,
            bundle_id=BUNDLE_ID,
        )


def test_union_requires_bundle_identity_and_safe_customer_pattern():
    with pytest.raises(CandidateUnionError, match="bundle_id"):
        union_candidate_sources(
            scoring_date="2020-07-15", spine_type="active_day", groups=_groups(),
            source_artifacts=_sources(), config=CONFIG, article_first_seen=FIRST_SEEN,
            bundle_id="",
        )
    groups = _groups()
    groups[0]["customer_key"] = "b" * 64
    with pytest.raises(CandidateUnionError, match="raw 64-hex"):
        union_candidate_sources(
            scoring_date="2020-07-15", spine_type="active_day", groups=groups,
            source_artifacts=_sources(), config=CONFIG, article_first_seen=FIRST_SEEN,
            bundle_id=BUNDLE_ID,
        )


def test_every_source_enforces_strict_article_eligibility():
    sources = _sources()
    sources["ann"]["rows"] = [
        {"customer_key": "synthetic_c1", "article_id": "future", "source_rank": 1}
    ]
    with pytest.raises(CandidateUnionError, match="ineligible article"):
        union_candidate_sources(
            scoring_date="2020-07-15", spine_type="active_day", groups=_groups(),
            source_artifacts=sources, config=CONFIG, article_first_seen=FIRST_SEEN,
            bundle_id=BUNDLE_ID,
        )


def test_source_duplicate_rank_fails():
    sources = _sources()
    sources["ann"]["rows"].append(
        {"customer_key": "synthetic_c1", "article_id": "a1", "source_rank": 1}
    )
    with pytest.raises(CandidateUnionError, match="duplicate rank"):
        union_candidate_sources(
            scoring_date="2020-07-15", spine_type="active_day", groups=_groups(),
            source_artifacts=sources, config=CONFIG, article_first_seen=FIRST_SEEN,
            bundle_id=BUNDLE_ID,
        )


def test_validated_daily_ann_partition_adapts_to_union_source(tmp_path):
    rows = [
        {"customer_id": "synthetic_c1", "day_index": 664, "article_id": "a1", "source": "ann", "source_rank": 1}
    ]
    write_daily_ann_partition(
        tmp_path, scoring_date="2020-07-15", day_index=664,
        bundle_id="v2_pit_safe_synthetic_fixture",
        candidate_config_id=CONFIG.candidate_config_id, cohort_id="synthetic",
        spine_type="active_day", depth=50, eligible_article_count=2, rows=rows,
        input_hashes=INPUT_HASHES,
    )
    artifact = daily_ann_to_candidate_source(
        read_daily_ann_partition(tmp_path, "2020-07-15")
    )
    assert artifact["source"] == "ann"
    assert artifact["rows"] == [
        {"customer_key": "synthetic_c1", "article_id": "a1", "source_rank": 1}
    ]
