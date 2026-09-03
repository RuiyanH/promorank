from __future__ import annotations

import pytest

from marketrank.candidate_pipeline.spines import (
    SpineError,
    build_active_day_spine,
    build_replay_day_spine,
)
from marketrank.jobs import build_candidates as job


def _source(spark, rows):
    return spark.createDataFrame(
        rows,
        "customer_id string, day_index int, article_id string, source_rank int",
    )


@pytest.mark.spark
def test_union_daily_v2_matches_frozen_rank_and_membership_semantics(spark):
    sources = {
        "repurchase": _source(spark, [("synthetic_c1", 664, "a1", 1)]),
        "category_pop": _source(spark, [("synthetic_c1", 664, "a2", 1)]),
        "global_pop": _source(
            spark,
            [("synthetic_c1", 664, "a1", 2), ("synthetic_c2", 664, "a2", 1)],
        ),
        "covisit": _source(spark, [("synthetic_c1", 664, "a2", 1)]),
        "ann": _source(spark, [("synthetic_c1", 664, "a2", 2)]),
    }
    output = job.union_daily_v2(sources, job.SOURCE_ORDER, spine_type="active_day")
    assert output.columns == [
        "customer_id", "day_index", "article_id", "spine_type",
        "repurchase_rank", "category_pop_rank", "global_pop_rank", "covisit_rank", "ann_rank",
        "from_repurchase", "from_category_pop", "from_global_pop", "from_covisit", "from_ann",
        "source_count",
    ]
    rows = {(row.customer_id, row.article_id): row.asDict() for row in output.collect()}
    assert rows[("synthetic_c1", "a1")]["source_count"] == 2
    assert rows[("synthetic_c1", "a1")]["ann_rank"] is None
    assert rows[("synthetic_c1", "a2")]["ann_rank"] == 2
    assert rows[("synthetic_c1", "a2")]["source_count"] == 3
    assert rows[("synthetic_c2", "a2")]["from_global_pop"] is True
    assert rows[("synthetic_c2", "a2")]["from_ann"] is False
    assert {row.spine_type for row in output.collect()} == {"active_day"}


@pytest.mark.spark
def test_union_daily_v1_schema_remains_legacy(spark):
    sources = {name: _source(spark, [("synthetic_c1", 664, "a1", 1)]) for name in job.SOURCE_ORDER}
    output = job.union_daily(sources, job.SOURCE_ORDER)
    assert "spine_type" not in output.columns
    assert "ann_rank" not in output.columns
    assert {"sources", "best_source_rank", "n_sources", "from_ann"} <= set(output.columns)


@pytest.mark.spark
def test_active_and_replay_spines_are_distinct_and_outcome_free(spark):
    active_input = spark.createDataFrame(
        [("synthetic_c1", 664, "a1"), ("synthetic_c1", 664, "a2")],
        "customer_id string, day_index int, article_id string",
    )
    active = build_active_day_spine(active_input)
    assert active.count() == 1
    assert active.columns == ["customer_id", "day_index", "spine_type"]
    assert active.collect()[0].spine_type == "active_day"

    cohort = spark.createDataFrame([("synthetic_c1",), ("synthetic_c2",)], "customer_id string")
    replay = build_replay_day_spine(spark, cohort, [664, 665])
    assert replay.count() == 4
    assert replay.columns == ["customer_id", "day_index", "spine_type"]
    assert {row.spine_type for row in replay.collect()} == {"replay_day"}


@pytest.mark.spark
def test_replay_spine_rejects_outcome_columns(spark):
    cohort = spark.createDataFrame(
        [("synthetic_c1", "a1")], "customer_id string, article_id string"
    )
    with pytest.raises(SpineError, match="outcome fields"):
        build_replay_day_spine(spark, cohort, [664])
