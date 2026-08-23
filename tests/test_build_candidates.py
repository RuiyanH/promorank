"""
Guards on C1's orchestrator -- the ANN snapshot adapter and its contract.

The snapshot adapter exists so `--checksum-day` can gate the 692-day job with
zero GPU work: the shipped `r2_recency` parquet IS the day-692 object. That
convenience is one flag away from being the worst leak available here -- stamp a
single day's retrieval across 692 days and every downstream number improves,
which is the failure mode nothing else in the pipeline would flag.

So the guard is tested, not just written.
"""

import json

import pytest
from pyspark.sql import functions as F

from marketrank.jobs import build_candidates as BC


# ---------------------------------------------------------------------------
# The single-day restriction
# ---------------------------------------------------------------------------
def test_snapshot_allowed_on_exactly_its_own_day():
    BC.assert_snapshot_single_day(692, 692, "snap.parquet", 692)  # no raise


def test_snapshot_refused_across_a_range():
    """The leak: 2020-08-12's retrieval stamped onto every training day."""
    with pytest.raises(SystemExit) as e:
        BC.assert_snapshot_single_day(90, 691, "snap.parquet", 692)
    assert "single-day fixture" in str(e.value)


def test_snapshot_refused_on_the_wrong_single_day():
    """One day, but not the snapshot's day -- still every row mis-stamped."""
    with pytest.raises(SystemExit):
        BC.assert_snapshot_single_day(500, 500, "snap.parquet", 692)


def test_no_snapshot_means_no_restriction():
    """The real run passes None here and must not be constrained by this guard."""
    BC.assert_snapshot_single_day(90, 691, None, 692)


@pytest.mark.parametrize("lo,hi", [(691, 692), (692, 693), (0, 692)])
def test_ranges_touching_the_snapshot_day_are_still_refused(lo, hi):
    """
    Containing the day is not the same as BEING the day.

    An off-by-one that let `691..692` through would stamp day 691 with day 692's
    retrieval -- a one-day leak, which is exactly as wrong as a 692-day one and
    much harder to notice.
    """
    with pytest.raises(SystemExit):
        BC.assert_snapshot_single_day(lo, hi, "snap.parquet", 692)


# ---------------------------------------------------------------------------
# The ANN contract -- one definition, binding on the future GPU stage
# ---------------------------------------------------------------------------
def _ann(spark, rows):
    from pyspark.sql.types import IntegerType, StringType, StructField, StructType

    schema = StructType(
        [
            StructField("customer_id", StringType(), False),
            StructField("day_index", IntegerType(), False),
            StructField("article_id", StringType(), False),
            StructField("source_rank", IntegerType(), False),
        ]
    )
    return spark.createDataFrame(rows, schema)


@pytest.mark.spark
def test_ann_contract_accepts_the_agreed_shape(spark):
    df = _ann(spark, [("c1", 692, "A", 1), ("c1", 692, "B", 50)])
    assert BC.assert_ann_contract(df).columns == list(BC.ANN_COLUMNS)


@pytest.mark.spark
def test_ann_contract_rejects_a_missing_column(spark):
    """
    The GPU stage will be written later and separately. If it forgets
    `day_index`, the union silently degenerates -- so the contract names it.
    """
    df = _ann(spark, [("c1", 692, "A", 1)]).drop("day_index")
    with pytest.raises(SystemExit) as e:
        BC.assert_ann_contract(df)
    assert "day_index" in str(e.value)


@pytest.mark.spark
def test_ann_contract_rejects_ranks_outside_the_budget(spark):
    """
    `source_rank > top_n` means the ANN stage emitted a deeper list than the
    shipped 50, which silently changes the slot budget and therefore every
    marginal-per-slot number R.6's rule reads.
    """
    df = _ann(spark, [("c1", 692, "A", 1), ("c1", 692, "B", 51)])
    with pytest.raises(SystemExit):
        BC.assert_ann_contract(df)


@pytest.mark.spark
def test_ann_contract_rejects_rank_zero(spark):
    """Ranks are 1-based everywhere in this build; 0 would shift the whole list."""
    df = _ann(spark, [("c1", 692, "A", 0)])
    with pytest.raises(SystemExit):
        BC.assert_ann_contract(df)


# ---------------------------------------------------------------------------
# The reference the checksum asserts against
# ---------------------------------------------------------------------------
def test_shipped_reference_is_present_and_has_every_source():
    """
    The checksum reads its expectations from the tracked artifact rather than
    from constants in the job, so the asserted number and the published one
    cannot drift. That only holds while the artifact is actually in the repo --
    B2 tracked it; this fails loudly if it is ever untracked again.
    """
    ref = json.loads(BC.SHIPPED_CEILING.read_text())
    ceiling = ref["ceiling"]
    assert abs(ceiling["recall_ceiling"] - 0.11929576468924556) < 1e-12
    for name in BC.SOURCE_ORDER:
        assert f"by_{name}" in ceiling, f"reference has no solo for {name}"


# ---------------------------------------------------------------------------
# Chunking. Cost knob, not a correctness knob -- but it decides which days each
# chunk covers, and a gap or an overlap there is silent: days would simply be
# missing from the table, or written twice under different anchors.
# ---------------------------------------------------------------------------
def test_chunks_cover_every_day_exactly_once():
    anchors = list(range(90, 692, 7))
    chunks = BC.chunks_for(anchors, 7, 90, 691, 4)
    covered = [d for c in chunks for d in range(c["lo"], c["hi"] + 1)]
    assert covered == sorted(covered), "chunks are out of order"
    assert len(covered) == len(set(covered)), "a day is written by two chunks"
    assert set(covered) == set(range(90, 692)), "a day is missing from every chunk"


def test_chunk_days_only_use_anchors_the_chunk_reads():
    """
    A day whose anchor is not in its chunk would join against nothing and lose
    covisit entirely -- no error, just a source silently contributing zero.
    """
    anchors = list(range(90, 692, 7))
    for c in BC.chunks_for(anchors, 7, 90, 691, 4):
        for d in range(c["lo"], c["hi"] + 1):
            anchor = ((d - 692) // 7) * 7 + 692
            assert anchor in c["anchors"], f"day {d} needs anchor {anchor}"


def test_chunk_width_changes_grouping_not_coverage():
    """Width is a cost knob: every width must cover the same days."""
    anchors = list(range(90, 692, 7))
    cover = {
        w: sorted(d for c in BC.chunks_for(anchors, 7, 90, 691, w)
                  for d in range(c["lo"], c["hi"] + 1))
        for w in (1, 2, 4, 13)
    }
    assert len({tuple(v) for v in cover.values()}) == 1
    assert len(BC.chunks_for(anchors, 7, 90, 691, 1)) > len(
        BC.chunks_for(anchors, 7, 90, 691, 4)
    )


def test_chunk_content_args_exclude_the_cost_knobs():
    """
    `chunk_weeks` and `cadence` decide which chunks exist, not what a day
    contains. Including them would force a full rebuild every time the width is
    tuned, for no changed row -- the same reasoning as the pairs job.
    """
    assert "chunk_weeks" not in BC.CHUNK_CONTENT_ARGS
    assert "cadence" not in BC.CHUNK_CONTENT_ARGS
    for k in ("n_repurchase", "n_category", "n_global_pop", "n_covisit",
              "covisit_lookback", "covisit_max_basket", "recent_k"):
        assert k in BC.CHUNK_CONTENT_ARGS, f"{k} changes content but is not compared"


# ---------------------------------------------------------------------------
# union_daily vs union_candidates. The docstring claims restricting to one day
# yields exactly the single-day version's output -- that claim is what makes the
# checksum a test of the writer rather than of a parallel implementation, and
# every other equivalence claim in this build has a test. The checksum itself
# would catch a divergence, but only on misha; this runs in CI.
# ---------------------------------------------------------------------------
def _src(spark, rows):
    from pyspark.sql.types import IntegerType, StringType, StructField, StructType

    return spark.createDataFrame(
        rows,
        StructType([
            StructField("customer_id", StringType(), False),
            StructField("day_index", IntegerType(), False),
            StructField("article_id", StringType(), False),
            StructField("source_rank", IntegerType(), False),
        ]),
    )


def _overlapping_sources(spark, day, other_day):
    """Candidates shared across sources, plus a second day that must not leak in."""
    from marketrank import candidates as C

    return {
        C.SOURCE_REPURCHASE: _src(spark, [
            ("c1", day, "A", 1), ("c1", day, "B", 2), ("c2", day, "C", 1),
            ("c1", other_day, "Z", 1),
        ]),
        C.SOURCE_CATEGORY: _src(spark, [
            ("c1", day, "B", 3), ("c2", day, "D", 7), ("c1", other_day, "Z", 2),
        ]),
        C.SOURCE_GLOBAL_POP: _src(spark, [
            ("c1", day, "A", 5), ("c2", day, "C", 5), ("c1", other_day, "Y", 1),
        ]),
        C.SOURCE_COVISIT: _src(spark, [("c1", day, "E", 2), ("c2", day, "D", 1)]),
        C.SOURCE_ANN: _src(spark, [("c1", day, "A", 9), ("c2", day, "F", 4)]),
    }


@pytest.mark.spark
def test_union_daily_restricted_to_one_day_equals_union_candidates(spark):
    from marketrank import candidates as C

    day, other = 692, 685
    sources = _overlapping_sources(spark, day, other)
    names = BC.source_names(sources)

    daily = BC.union_daily(sources, names).filter(F.col("day_index") == day)
    single = C.union_candidates(
        *[
            sources[n].filter(F.col("day_index") == day)
            .drop("day_index")
            .withColumn("source", F.lit(n))
            for n in names
        ],
        source_names=names,
    )

    cols = ["customer_id", "article_id", "n_sources", "best_source_rank"] + [
        f"from_{n}" for n in names
    ]
    got = sorted(tuple(r) for r in daily.select(*cols).collect())
    want = sorted(tuple(r) for r in single.select(*cols).collect())
    assert got == want

    # And the other day is genuinely excluded rather than merged in -- an
    # unpartitioned group key would fold "Z" from day 685 into day 692's rows.
    assert not any(r[1] in ("Y", "Z") for r in got)


@pytest.mark.spark
def test_union_daily_keeps_days_separate(spark):
    """
    Same (customer, article) on two days must stay two rows.

    Dropping `day_index` from the group key would collapse them and take
    `min(source_rank)` across days -- a candidate ranked by information from a
    day it cannot see.
    """
    from marketrank import candidates as C

    sources = dict.fromkeys(BC.SOURCE_ORDER)
    for n in BC.SOURCE_ORDER:
        sources[n] = _src(spark, [("c1", 692, "A", 9), ("c1", 685, "A", 1)])
    out = BC.union_daily(sources, BC.source_names(sources))

    rows = {(r.day_index, r.best_source_rank) for r in out.collect()}
    assert rows == {(692, 9), (685, 1)}, rows


# ---------------------------------------------------------------------------
# Missing sources
# ---------------------------------------------------------------------------
def test_source_names_requires_all_five():
    from marketrank import candidates as C

    complete = dict.fromkeys(BC.SOURCE_ORDER, object())
    assert BC.source_names(complete) == BC.SOURCE_ORDER

    partial = {n: object() for n in BC.SOURCE_ORDER if n != C.SOURCE_ANN}
    with pytest.raises(SystemExit) as e:
        BC.source_names(partial)
    assert C.SOURCE_ANN in str(e.value)
