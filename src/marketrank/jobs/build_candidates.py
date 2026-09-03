"""
Candidate generation at ranker scale, per-day `as_of` -- C1's orchestrator.

    # gate the whole job on zero GPU work, before generating anything
    python -m marketrank.jobs.build_candidates --checksum-day \\
        --ann-snapshot artifacts/twotower/runs/r2_recency/ann_candidates.parquet

    # the real run
    python -m marketrank.jobs.build_candidates --lo-day 90 --hi-day 691

**THE CHECKSUM COMES FIRST, AND IT IS DECOMPOSED.** Restricting this machinery
to the `val_tune` cohort on day 692 must reproduce the shipped table exactly --
not just the 11.930% union, but all five per-source solos. A union that matches
tells you nothing broke; five solos tell you WHICH source moved when something
does. The reference is read from the shipped artifact
(`artifacts/candidates_misha_90_50/ceiling.json`, tracked in git as of B2)
rather than transcribed into this file, so the number the checksum asserts and
the number the README quotes cannot drift apart.

It costs no GPU time, because the shipped `r2_recency` ANN parquet IS the day-692
snapshot -- see `--ann-snapshot` below. So this gates the 692-day run before the
expensive stage exists.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, functions as F

from marketrank import candidates as C, candidates_daily as CD, config, partitions as PT
from marketrank.candidate_pipeline.config import load_candidate_config
from marketrank.candidate_pipeline.guards import assert_large_output_path
from marketrank.candidate_pipeline.spines import build_active_day_spine, build_replay_day_spine
from marketrank.retrieval import baselines as B
from marketrank.retrieval.daily_ann import read_daily_ann_range, validate_daily_ann_range

SHIPPED_CEILING = Path("artifacts/candidates_misha_90_50/ceiling.json")

# What the shipped ANN snapshot must look like. Asserted on read rather than
# trusted: this file is the checksum's only unverified input.
ANN_SNAPSHOT_ROWS = 1_000_000
ANN_SNAPSHOT_CUSTOMERS = 20_000
ANN_SNAPSHOT_TOP_N = 50

SOURCE_ORDER = (
    C.SOURCE_REPURCHASE,
    C.SOURCE_CATEGORY,
    C.SOURCE_GLOBAL_POP,
    C.SOURCE_COVISIT,
    C.SOURCE_ANN,
)

# Tolerance on the checksum. The per-day machinery is deterministic and should
# reproduce the shipped numbers to the pair, so this is a float-comparison
# guard, not a margin for "close enough". A real regression moves recall by
# orders of magnitude more than this.
CHECKSUM_TOL = 1e-9


# ---------------------------------------------------------------------------
# The ANN contract. ONE definition, exercised by the checksum today and binding
# on the GPU stage when it exists -- so the expensive path is validated by the
# same assertion the cheap path already runs, rather than by a second one
# written later and never tested.
# ---------------------------------------------------------------------------
ANN_COLUMNS = ("customer_id", "day_index", "article_id", "source_rank")


def assert_ann_contract(df: DataFrame, top_n: int = ANN_SNAPSHOT_TOP_N) -> DataFrame:
    """Every ANN producer -- snapshot or per-day GPU -- returns this shape."""
    missing = [c for c in ANN_COLUMNS if c not in df.columns]
    if missing:
        raise SystemExit(f"ANN output is missing columns {missing}; got {df.columns}")
    bad = df.filter(
        (F.col("source_rank") < 1) | (F.col("source_rank") > top_n)
    ).limit(1).count()
    if bad:
        raise SystemExit(f"ANN output has source_rank outside 1..{top_n}")
    return df.select(*ANN_COLUMNS)


def load_ann_snapshot(
    spark: SparkSession, path: Path, day: int, strict: bool = True
) -> tuple[DataFrame, dict]:
    """
    Read a SINGLE-DAY ANN parquet and stamp it to `day`.

    A CHECKSUM FIXTURE, NOT AN INPUT. The shipped `r2_recency` export is the
    day-692 object by construction -- customer features as of d-1 = 2020-08-11,
    `as_of` = `val_tune`'s first day -- so stamping it to 692 is legitimate.
    Stamping it across a multi-day run would score every day with 2020-08-12's
    retrieval, which is the per-day-ANN leak in its purest form. The caller
    enforces the single-day restriction; this function records what it read.
    """
    df = spark.read.parquet(str(path))
    n_rows = df.count()
    n_cust = df.select("customer_id").distinct().count()
    max_rank = df.agg(F.max("source_rank")).collect()[0][0]

    if strict:
        problems = []
        if n_rows != ANN_SNAPSHOT_ROWS:
            problems.append(f"rows {n_rows} != {ANN_SNAPSHOT_ROWS}")
        if n_cust != ANN_SNAPSHOT_CUSTOMERS:
            problems.append(f"customers {n_cust} != {ANN_SNAPSHOT_CUSTOMERS}")
        if max_rank is None or max_rank > ANN_SNAPSHOT_TOP_N:
            problems.append(f"max source_rank {max_rank} > {ANN_SNAPSHOT_TOP_N}")
        if problems:
            raise SystemExit(
                f"ANN snapshot at {path} is not the shipped day-{day} object: "
                + "; ".join(problems)
            )

    meta = {
        "path": str(path),
        "sha256": _content_hash(path),
        "rows": n_rows,
        "customers": n_cust,
        "max_source_rank": int(max_rank) if max_rank is not None else None,
        "stamped_day": int(day),
    }
    stamped = df.withColumn("day_index", F.lit(int(day)))
    return assert_ann_contract(stamped), meta


def _content_hash(path: Path) -> str:
    """sha256 over the file, or over every part in deterministic order."""
    h = hashlib.sha256()
    files = [path] if path.is_file() else sorted(
        p for p in path.rglob("*") if p.is_file() and not p.name.startswith(".")
    )
    for f in files:
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
def build_sources(
    spark: SparkSession,
    events: DataFrame,
    pairs: DataFrame,
    phase: int,
    cadence: int = CD.COVISIT_CADENCE_DAYS,
    ann: DataFrame | None = None,
    n_repurchase: int = 30,
    n_category: int = 40,
    n_global_pop: int = 40,
    n_covisit: int = 60,
    recent_k: int = 10,
    covisit_lookback: int = 90,
    covisit_max_basket: int = 50,
    global_pop_df: DataFrame | None = None,
    category_pop_df: DataFrame | None = None,
) -> dict[str, DataFrame]:
    """All five sources in one shape: (customer_id, day_index, article_id, source_rank)."""
    out: dict[str, DataFrame] = {}

    out[C.SOURCE_REPURCHASE] = CD.daily_repurchase(spark, events, n=n_repurchase)

    dom = CD.daily_dominant_category(spark, events)
    cat = category_pop_df if category_pop_df is not None else CD.daily_category_pop(spark, n=n_category)
    out[C.SOURCE_CATEGORY] = dom.join(
        cat, ["day_index", "product_type_no"], "inner"
    ).select("customer_id", "day_index", "article_id", "source_rank")

    gp = global_pop_df if global_pop_df is not None else CD.daily_global_pop(spark, n=n_global_pop)
    out[C.SOURCE_GLOBAL_POP] = events.join(gp, "day_index", "inner").select(
        "customer_id", "day_index", "article_id", "source_rank"
    )

    out[C.SOURCE_COVISIT] = CD.daily_covisit(
        spark, events, pairs, n=n_covisit, recent_k=recent_k,
        lookback_days=covisit_lookback, max_basket=covisit_max_basket,
        cadence_days=cadence, phase=phase,
    )

    if ann is not None:
        out[C.SOURCE_ANN] = ann
    return out


CHUNK_KEY = "chunk"
# What changes the CONTENT of a chunk. `chunk_weeks` and `cadence` decide which
# chunks exist and which anchors each reads, not what a given day contains --
# same reasoning as the pairs job, so tuning the width does not force a rebuild.
CHUNK_CONTENT_ARGS = (
    "n_repurchase", "n_category", "n_global_pop", "n_covisit",
    "covisit_lookback", "covisit_max_basket", "recent_k",
    "ann_root", "ann_bundle_id", "ann_candidate_config_id", "ann_cohort_id",
    "spine_type", "ann_partition_checksums",
)


def union_daily(sources: dict[str, DataFrame], names: tuple[str, ...]) -> DataFrame:
    """
    `candidates.union_candidates` with `day_index` in the group key.

    Same semantics deliberately -- one row per (customer, day, article) carrying
    every source that produced it, because a candidate reachable from two
    sources is a different object from one reachable from a single source, and
    the ranker should see that. Restricting the output of this to one day yields
    exactly what the single-day version returns, which is what makes the
    checksum a test of the writer rather than of a parallel implementation.
    """
    from functools import reduce

    tagged = [sources[n].withColumn("source", F.lit(n)) for n in names]
    out = (
        reduce(lambda a, b: a.unionByName(b), tagged)
        .groupBy("customer_id", "day_index", "article_id")
        .agg(
            F.collect_set("source").alias("sources"),
            F.min("source_rank").alias("best_source_rank"),
        )
        .withColumn("n_sources", F.size("sources"))
    )
    for name in names:
        out = out.withColumn(f"from_{name}", F.array_contains("sources", name))
    return out


def union_daily_v2(
    sources: dict[str, DataFrame],
    names: tuple[str, ...],
    *,
    spine_type: str,
) -> DataFrame:
    """V2 union with fixed nullable ranks, flags, count, and spine grain."""

    from functools import reduce

    if names != SOURCE_ORDER:
        raise SystemExit(f"V2 candidate union requires ordered sources {list(SOURCE_ORDER)}")
    if spine_type not in {"active_day", "replay_day"}:
        raise SystemExit(f"invalid V2 spine_type: {spine_type}")
    tagged = [sources[name].withColumn("source", F.lit(name)) for name in names]
    combined = reduce(lambda left, right: left.unionByName(right), tagged)
    aggregations = [
        F.min(F.when(F.col("source") == name, F.col("source_rank"))).alias(f"{name}_rank")
        for name in names
    ]
    out = combined.groupBy("customer_id", "day_index", "article_id").agg(*aggregations)
    for name in names:
        out = out.withColumn(f"from_{name}", F.col(f"{name}_rank").isNotNull())
    count_expression = sum(
        (F.col(f"from_{name}").cast("int") for name in names),
        F.lit(0),
    )
    return out.withColumn("source_count", count_expression).withColumn(
        "spine_type", F.lit(spine_type)
    ).select(
        "customer_id",
        "day_index",
        "article_id",
        "spine_type",
        *(f"{name}_rank" for name in names),
        *(f"from_{name}" for name in names),
        "source_count",
    )


def chunks_for(anchors: list[int], cadence: int, lo: int, hi: int, width: int) -> list[dict]:
    """
    Group anchors into chunks of `width` weeks, with the days each one covers.

    WHY CHUNK AT ALL. One plan over 692 days puts the whole repurchase fan-out
    (585M intermediate rows) inside a single stage. Chunking does not reduce that
    total -- it sums to the same across chunks -- but no single stage carries it,
    and each chunk's write is the action that truncates the lineage, which is the
    actual mechanism bounding plan size and peak shuffle.

    WHY NOT WEEKLY. One anchor-week is ~12.4k events/day x 7 x 159 candidates
    ~= 14M rows, which is under-sized for a Spark stage: fixed planning and
    scheduling overhead becomes a visible fraction of each chunk. Four weeks is
    ~55M rows over ~25 chunks. Width 1 stays available for debugging and is what
    the checksum uses.
    """
    out = []
    for i in range(0, len(anchors), width):
        g = anchors[i:i + width]
        d_lo, d_hi = max(lo, g[0]), min(hi, g[-1] + cadence - 1)
        if d_lo <= d_hi:
            out.append({"chunk": int(g[0]), "anchors": [int(x) for x in g],
                        "lo": int(d_lo), "hi": int(d_hi)})
    return out


def materialize_shared(
    spark: SparkSession, out: Path, name: str, build, args: dict,
    content_args: tuple[str, ...], lo: int, hi: int, force: bool = False,
) -> DataFrame:
    """
    Compute a range-wide intermediate ONCE and read it back.

    `daily_global_pop` and `daily_category_pop` are customer-independent and
    tiny -- tens of thousands and a few million rows over the whole range -- but
    each one carries an explode grid over every article-day. Rebuilding them
    inside 25 chunks is pure waste, and worse, it makes per-chunk runtime
    misleading about where the cost actually is.

    Per-EVENT work stays in the chunk, where its fan-out is bounded by the
    chunk's own events.
    """
    key, value = "range", f"{lo}_{hi}"
    path = PT.part_path(out / name, key, value)
    state = PT.part_state(out / name, key, value, args, content_args)
    if state == PT.MISMATCH and not force:
        raise SystemExit(
            f"{name} exists for range {value} under different args "
            f"{PT.read_part_meta(out / name, key, value).get('args')} != {args}"
        )
    if state != PT.OK:
        df = build().filter(F.col("day_index").between(lo, hi))
        df.write.mode("overwrite").parquet(str(path))
        n = spark.read.parquet(str(path)).count()
        PT.write_part_meta(out / name, key, value,
                           {"range": [lo, hi], "rows": int(n), "args": args})
        print(f"SHARED {name:<20} rows {n:>10} -> {path}")
    else:
        print(f"SHARED {name:<20} reused    -> {path}")
    return spark.read.parquet(str(path))


def content_of(a, ann_manifests: list[dict] | None = None) -> dict:
    """The chunk's content arguments, including the exact daily ANN identity."""

    return {
        "n_repurchase": a.n_repurchase,
        "n_category": a.n_category,
        "n_global_pop": a.n_global_pop,
        "n_covisit": a.n_covisit,
        "covisit_lookback": a.covisit_lookback,
        "covisit_max_basket": a.covisit_max_basket,
        "recent_k": a.recent_k,
        "ann_root": str(a.ann_root.resolve()) if a.ann_root is not None else None,
        "ann_bundle_id": a.ann_bundle_id,
        "ann_candidate_config_id": a.ann_candidate_config_id,
        "ann_cohort_id": a.ann_cohort_id,
        "spine_type": a.spine_type,
        "ann_partition_checksums": (
            [
                {
                    "scoring_date": manifest["scoring_date"],
                    "partition_checksum": manifest["partition_checksum"],
                    "manifest_checksum": hashlib.sha256(
                        (
                            json.dumps(
                                manifest,
                                sort_keys=True,
                                separators=(",", ":"),
                                ensure_ascii=True,
                            )
                            + "\n"
                        ).encode()
                    ).hexdigest(),
                    "input_hashes": manifest["input_hashes"],
                }
                for manifest in sorted(ann_manifests, key=lambda item: item["scoring_date"])
            ]
            if ann_manifests is not None
            else None
        ),
    }


def write_chunk(
    spark, out: Path, ch: dict, union: DataFrame, content: dict,
    extra: dict | None = None,
) -> int:
    """Write one chunk and record metadata only after Spark commits it."""

    import time as _time

    t0 = _time.time()
    path = PT.part_path(out, CHUNK_KEY, ch["chunk"])
    union.write.mode("overwrite").partitionBy("day_index").parquet(str(path))
    rows = spark.read.parquet(str(path)).count()
    meta = {
        "chunk": ch["chunk"],
        "anchors": ch["anchors"],
        "day_range": [ch["lo"], ch["hi"]],
        "rows": int(rows),
        "seconds": round(_time.time() - t0, 1),
        "args": content,
    }
    meta.update(extra or {})
    PT.write_part_meta(out, CHUNK_KEY, ch["chunk"], meta)
    print(
        f"CHUNK {ch['chunk']:>5}  days {ch['lo']}..{ch['hi']}  "
        f"rows {rows:>10}  {_time.time() - t0:6.1f}s"
    )
    return int(rows)


def load_ann_root_for_days(
    spark: SparkSession,
    root: Path,
    days: list[int],
    *,
    bundle_id: str | None = None,
    candidate_config_id: str | None = None,
    cohort_id: str | None = None,
    spine_type: str = "active_day",
    expected_partition_checksums: dict[str, str] | None = None,
) -> tuple[DataFrame, list[dict]]:
    """Load only requested checksum-validated daily ANN partitions."""

    zero = _dt.date.fromisoformat(CD.ft.DAY_ZERO)
    dates = [(zero + _dt.timedelta(days=day)).isoformat() for day in days]
    expected = {"spine_type": spine_type}
    for key, value in {
        "bundle_id": bundle_id,
        "candidate_config_id": candidate_config_id,
        "cohort_id": cohort_id,
    }.items():
        if value is not None:
            expected[key] = value
    loaded = read_daily_ann_range(root, dates, expected=expected)
    if expected_partition_checksums is not None:
        actual = {
            manifest["scoring_date"]: manifest["partition_checksum"]
            for manifest in loaded["partitions"]
        }
        if actual != expected_partition_checksums:
            raise SystemExit("daily ANN partition changed after resume preflight")
    by_date = {manifest["scoring_date"]: manifest for manifest in loaded["partitions"]}
    for day, date in zip(days, dates, strict=True):
        if by_date[date]["day_index"] != day:
            raise SystemExit(
                f"daily ANN partition {date} declares day_index {by_date[date]['day_index']} != {day}"
            )
    schema = "customer_id string, day_index int, article_id string, source string, source_rank int"
    frame = spark.createDataFrame(
        [tuple(row[key] for key in ("customer_id", "day_index", "article_id", "source", "source_rank"))
         for row in loaded["rows"]],
        schema=schema,
    )
    return assert_ann_contract(frame), loaded["partitions"]


def assert_ann_matches_spine(ann: DataFrame, spine: DataFrame) -> DataFrame:
    """Reject ANN rows outside the exact customer/day scoring spine."""

    keys = ["customer_id", "day_index"]
    spine_keys = spine.select(*keys).distinct()
    outside = ann.select(*keys).distinct().join(spine_keys, keys, "left_anti").limit(1).count()
    if outside:
        raise SystemExit("daily ANN contains a customer/day outside the requested scoring spine")
    return ann.join(spine_keys, keys, "inner")


def source_names(sources: dict) -> tuple[str, ...]:
    """
    Every candidate table carries ALL five sources, or the job stops.

    `tuple(n for n in SOURCE_ORDER if n in sources)` reads as defensive and is
    the opposite: a source missing from the dict would be silently dropped, the
    slot budget would change, and every marginal-per-slot number R.6's rule
    reads would move -- with nothing raising. That is the same silent-skip class
    the chunk-coverage tests exist to catch, so it gets the same treatment.
    """
    missing = [n for n in SOURCE_ORDER if n not in sources]
    if missing:
        raise SystemExit(
            f"missing candidate source(s): {missing}. All of {list(SOURCE_ORDER)} "
            "are required -- a dropped source changes the budget and every "
            "per-slot number without failing."
        )
    return SOURCE_ORDER


def run_checksum(spark, args, phase: int) -> dict:
    """
    Reproduce the shipped table on one day, source by source.

    Returns the comparison. Raises on any mismatch, naming the source -- which is
    the entire reason this is decomposed rather than a single union assertion.
    """
    ref = json.loads(Path(args.expect_from).read_text())
    ref_ceiling = ref["ceiling"]

    day = args.ann_snapshot_day
    cohort = spark.read.parquet("artifacts/twotower/eval_customers").select(
        "customer_id"
    ).distinct()
    truth = B.truth_pairs(spark, "val_tune").join(
        F.broadcast(cohort), "customer_id", "inner"
    )
    n_pairs = truth.count()
    if n_pairs != args.expect_pairs:
        raise SystemExit(
            f"denominator is {n_pairs}, expected {args.expect_pairs} -- the "
            "cohort moved and nothing below would be comparable"
        )

    events = cohort.withColumn("day_index", F.lit(int(day)))
    ann, ann_meta = load_ann_snapshot(spark, args.ann_snapshot, day)
    pairs = spark.read.parquet(str(args.pairs)).filter(
        F.col("anchor_day") == int(day)
    )
    if pairs.limit(1).count() == 0:
        raise SystemExit(
            f"no covisit pairs for anchor {day} under {args.pairs}. The checksum "
            "day must be an anchor -- that is what the val_tune phasing is for. "
            "Run covisit_pairs_table first."
        )

    sources = build_sources(
        spark, events, pairs, phase=phase, cadence=args.cadence, ann=ann,
        n_repurchase=args.n_repurchase, n_category=args.n_category,
        n_global_pop=args.n_global_pop, n_covisit=args.n_covisit,
        recent_k=args.recent_k, covisit_lookback=args.covisit_lookback,
        covisit_max_basket=args.covisit_max_basket,
    )
    names = source_names(sources)

    # THROUGH THE PRODUCTION WRITER, not beside it. A width-1 chunk exercises the
    # same union, the same partitioning and the same markers, so the gate tests
    # what the 692-day run will actually do rather than a sibling of it.
    #
    # To a SEPARATE directory, though: day 692 is `val_tune`. Writing it into the
    # candidates table week 5 globs would put an evaluation day into the ranker's
    # training set -- a leak created by the very thing meant to prevent leaks.
    ch = {"chunk": int(day), "anchors": [int(day)], "lo": int(day), "hi": int(day)}
    write_chunk(
        spark, args.checksum_out, ch, union_daily(sources, names), content_of(args),
        extra={"ann_snapshot": ann_meta, "checksum": True, "phase": phase},
    )
    written = spark.read.parquet(
        str(PT.part_path(args.checksum_out, CHUNK_KEY, int(day)))
    )
    union = written.filter(F.col("day_index") == int(day)).drop("day_index")
    got = C.recall_ceiling(union, truth, source_names=names)

    rows, failures = [], []
    for key in ("recall_ceiling", *(f"by_{n}" for n in names)):
        want, have = ref_ceiling[key], got[key]
        ok = abs(want - have) <= CHECKSUM_TOL
        rows.append((key, want, have, ok))
        if not ok:
            failures.append(key)

    print(f"\nCHECKSUM against {args.expect_from}  (day {day}, {n_pairs} pairs)")
    print(f"{'metric':<22}{'shipped':>12}{'got':>12}   ")
    for key, want, have, ok in rows:
        print(f"{key:<22}{want*100:>11.4f}%{have*100:>11.4f}%   {'ok' if ok else 'MISMATCH'}")

    result = {
        "day": int(day),
        "n_true_pairs": n_pairs,
        "reference": str(args.expect_from),
        "ann_snapshot": ann_meta,
        "metrics": {k: {"shipped": w, "got": g, "ok": o} for k, w, g, o in rows},
        "passed": not failures,
    }
    if failures:
        raise SystemExit(
            f"checksum FAILED on {failures} -- the per-day machinery does not "
            "reproduce the shipped table. Do not run the 692-day job."
        )
    print("CHECKSUM PASS")
    return result


def assert_snapshot_single_day(lo, hi, snapshot, snapshot_day) -> None:
    """
    A single-day snapshot may only ever serve a single-day run.

    Without this, `--ann-snapshot` on the 692-day job would stamp
    2020-08-12's retrieval onto every day in the range. That is the per-day-ANN
    leak in its purest form, and its symptom is every downstream number getting
    BETTER -- so nothing would flag it. The guard is the PIT rule applied to the
    adapter, not defensiveness about a flag.
    """
    if snapshot is None:
        return
    if (lo, hi) != (snapshot_day, snapshot_day):
        raise SystemExit(
            f"--ann-snapshot is a single-day fixture for day {snapshot_day}, but "
            f"the requested range is {lo}..{hi}. Stamping it across multiple days "
            "would score every one of them with that day's retrieval. Use the "
            "per-day ANN stage for a real run."
        )


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checksum-day", action="store_true",
                   help="reproduce the shipped table on the snapshot day and exit")
    p.add_argument("--lo-day", type=int, default=None)
    p.add_argument("--hi-day", type=int, default=None)
    p.add_argument("--cadence", type=int, default=CD.COVISIT_CADENCE_DAYS)
    p.add_argument("--n-repurchase", type=int, default=30)
    p.add_argument("--n-category", type=int, default=40)
    p.add_argument("--n-global-pop", type=int, default=40)
    p.add_argument("--n-covisit", type=int, default=60)
    p.add_argument("--recent-k", type=int, default=10)
    p.add_argument("--chunk-weeks", type=int, default=4,
                   help="anchor-weeks per chunk; 1 for debugging and the checksum")
    p.add_argument("--force", action="store_true")
    p.add_argument("--checksum-out", type=Path, default=None,
                   help="default: $MARKETRANK_TABLES/candidates_checksum -- kept "
                        "apart from the training table because day 692 is val_tune")
    p.add_argument("--covisit-lookback", type=int, default=90)
    p.add_argument("--covisit-max-basket", type=int, default=50)
    p.add_argument("--pairs", type=Path, default=None,
                   help="default: $MARKETRANK_TABLES/covisit_pairs")
    p.add_argument("--out", type=Path, default=None,
                   help="default: $MARKETRANK_TABLES/candidates")
    # THE SNAPSHOT ADAPTER. Named for what it is; guarded below.
    p.add_argument("--ann-snapshot", type=Path, default=None,
                   help="single-day ANN parquet, checksum fixture ONLY")
    p.add_argument("--ann-snapshot-day", type=int, default=None,
                   help="the day that snapshot belongs to; defaults to val_tune day 0")
    p.add_argument("--ann-root", type=Path, default=None,
                   help="V2 checksum-complete per-date ANN partition root")
    p.add_argument("--candidate-config", type=Path, default=None,
                   help="frozen candidate-config.v2 JSON; required with --ann-root")
    p.add_argument("--ann-bundle-id", default=None,
                   help="required bundle ID when reading --ann-root")
    p.add_argument("--ann-candidate-config-id", default=None,
                   help="required candidate config ID when reading --ann-root")
    p.add_argument("--ann-cohort-id", default=None,
                   help="required cohort/spine ID when reading --ann-root")
    p.add_argument("--spine-type", choices=("active_day", "replay_day"), default="active_day")
    p.add_argument("--cohort", type=Path, default=None,
                   help="fixed cohort parquet; required for replay_day V2 builds")
    p.add_argument("--scratch-root", type=Path, default=None,
                   help="approved scratch root; required with --ann-root")
    p.add_argument("--expect-from", type=Path, default=SHIPPED_CEILING)
    p.add_argument("--expect-pairs", type=int, default=70_715)
    p.add_argument("--driver-memory", default="48g")
    return p.parse_args(argv)


def prepare_args(a: argparse.Namespace) -> argparse.Namespace:
    """Resolve paths and fail unsafe/cross-contract inputs before Spark starts."""

    if a.pairs is None:
        a.pairs = config.TABLES / "covisit_pairs"
    if a.out is None:
        a.out = config.TABLES / "candidates"
    if a.checksum_out is None:
        a.checksum_out = config.TABLES / "candidates_checksum"
    if a.ann_snapshot is not None and a.ann_root is not None:
        raise SystemExit("choose exactly one of --ann-snapshot and --ann-root")
    if a.checksum_day:
        if a.ann_root is not None:
            raise SystemExit("--checksum-day uses the legacy single-day --ann-snapshot only")
        if a.ann_snapshot is None:
            raise SystemExit("--checksum-day needs --ann-snapshot")
        return a
    if a.ann_snapshot is None and a.ann_root is None:
        raise SystemExit(
            "no ANN source: pass --ann-root for V2 daily partitions or use the "
            "single-day --ann-snapshot checksum fixture"
        )
    if a.ann_root is not None:
        if a.candidate_config is None:
            raise SystemExit("--ann-root requires --candidate-config")
        if a.scratch_root is None:
            raise SystemExit("--ann-root requires --scratch-root")
        if not a.ann_bundle_id or not a.ann_cohort_id:
            raise SystemExit("--ann-root requires --ann-bundle-id and --ann-cohort-id")
        if a.spine_type == "replay_day" and a.cohort is None:
            raise SystemExit("replay_day --ann-root builds require --cohort")
        v2_config = load_candidate_config(a.candidate_config)
        a.n_repurchase = v2_config.depth("repurchase")
        a.n_category = v2_config.depth("category_pop")
        a.n_global_pop = v2_config.depth("global_pop")
        a.n_covisit = v2_config.depth("covisit")
        a.covisit_lookback = v2_config.raw["sources"]["covisit"]["lookback_days"]
        a.covisit_max_basket = v2_config.raw["sources"]["covisit"]["max_basket"]
        a.cadence = v2_config.raw["sources"]["covisit"]["cadence_days"]
        a.recent_k = v2_config.recent_k
        if a.ann_candidate_config_id not in (None, v2_config.candidate_config_id):
            raise SystemExit("--ann-candidate-config-id conflicts with --candidate-config")
        a.ann_candidate_config_id = v2_config.candidate_config_id
        assert_large_output_path(a.out, a.scratch_root)
    return a


def main(argv=None) -> dict:
    from marketrank.spark import get_spark

    a = prepare_args(parse_args(argv))
    spark = get_spark("build_candidates", driver_memory=a.driver_memory)
    spark.conf.set("spark.sql.adaptive.enabled", "true")
    spark.conf.set("spark.sql.adaptive.skewJoin.enabled", "true")

    phase = CD.covisit_phase(spark)
    if a.ann_snapshot_day is None:
        a.ann_snapshot_day = phase
    if a.checksum_day:
        return run_checksum(spark, a, phase)

    lo = CD.WARM_UP_DAYS if a.lo_day is None else a.lo_day
    hi = (phase - 1) if a.hi_day is None else a.hi_day
    assert_snapshot_single_day(lo, hi, a.ann_snapshot, a.ann_snapshot_day)

    anchors = CD.anchor_days_for(spark, lo, hi, a.cadence, phase)
    chunks = chunks_for(anchors, a.cadence, lo, hi, a.chunk_weeks)
    print(f"DAYS {lo}..{hi}  ANCHORS {len(anchors)}  "
          f"CHUNKS {len(chunks)} x {a.chunk_weeks}w  OUT {a.out}")

    # Range-wide and customer-independent: computed once, read by every chunk.
    gp = materialize_shared(
        spark, config.TABLES, "daily_global_pop",
        lambda: CD.daily_global_pop(spark, n=a.n_global_pop),
        {"n_global_pop": a.n_global_pop}, ("n_global_pop",), lo, hi, a.force)
    cat = materialize_shared(
        spark, config.TABLES, "daily_category_pop",
        lambda: CD.daily_category_pop(spark, n=a.n_category),
        {"n_category": a.n_category}, ("n_category",), lo, hi, a.force)

    keys = [c["chunk"] for c in chunks]
    manifests_by_day: dict[int, dict] = {}
    if a.ann_root is not None:
        requested_days = list(range(lo, hi + 1))
        requested_dates = [
            (_dt.date.fromisoformat(CD.ft.DAY_ZERO) + _dt.timedelta(days=day)).isoformat()
            for day in requested_days
        ]
        manifests = validate_daily_ann_range(
            a.ann_root,
            requested_dates,
            expected={
                "bundle_id": a.ann_bundle_id,
                "candidate_config_id": a.ann_candidate_config_id,
                "cohort_id": a.ann_cohort_id,
                "spine_type": a.spine_type,
            },
        )
        manifests_by_day = {manifest["day_index"]: manifest for manifest in manifests}
    content_by_chunk = {
        ch["chunk"]: content_of(
            a,
            [manifests_by_day[day] for day in range(ch["lo"], ch["hi"] + 1)]
            if manifests_by_day
            else None,
        )
        for ch in chunks
    }
    todo = []
    states = {}
    for ch in chunks:
        chunk_todo, chunk_states = PT.plan(
            a.out,
            CHUNK_KEY,
            [ch["chunk"]],
            content_by_chunk[ch["chunk"]],
            CHUNK_CONTENT_ARGS,
            force=a.force,
        )
        todo.extend(chunk_todo)
        states.update(chunk_states)
    print(f"STATE ok={len(keys) - len(todo)} todo={len(todo)}")

    all_pairs = spark.read.parquet(str(a.pairs))
    _zero = _dt.date.fromisoformat(CD.ft.DAY_ZERO)
    if a.ann_root is not None and a.spine_type == "replay_day":
        cohort = spark.read.parquet(str(a.cohort))
        events_all = build_replay_day_spine(spark, cohort, range(lo, hi + 1))
    else:
        events_all = build_active_day_spine(
            CD.scoring_events(
                spark,
                (_zero + _dt.timedelta(days=lo)).isoformat(),
                (_zero + _dt.timedelta(days=hi)).isoformat(),
            )
        )

    for ch in chunks:
        if ch["chunk"] not in todo:
            continue
        # Cached: repurchase, dominant-category and covisit seeds all join
        # against it, and without this the chunk's events are recomputed three
        # times from a 31.8M-row scan.
        events = events_all.filter(
            F.col("day_index").between(ch["lo"], ch["hi"])
        ).cache()
        pairs = all_pairs.filter(F.col("anchor_day").isin(ch["anchors"]))
        ann_meta = None
        if a.ann_root is not None:
            ann, ann_meta = load_ann_root_for_days(
                spark,
                a.ann_root,
                list(range(ch["lo"], ch["hi"] + 1)),
                bundle_id=a.ann_bundle_id,
                candidate_config_id=a.ann_candidate_config_id,
                cohort_id=a.ann_cohort_id,
                spine_type=a.spine_type,
                expected_partition_checksums={
                    manifests_by_day[day]["scoring_date"]: manifests_by_day[day]["partition_checksum"]
                    for day in range(ch["lo"], ch["hi"] + 1)
                },
            )
        else:
            ann, snapshot_meta = load_ann_snapshot(
                spark, a.ann_snapshot, a.ann_snapshot_day, strict=False
            )
            ann_meta = [snapshot_meta]
        ann = assert_ann_matches_spine(ann, events)
        sources = build_sources(
            spark, events, pairs, phase=phase, cadence=a.cadence, ann=ann,
            n_repurchase=a.n_repurchase, n_category=a.n_category,
            n_global_pop=a.n_global_pop, n_covisit=a.n_covisit,
            recent_k=a.recent_k, covisit_lookback=a.covisit_lookback,
            covisit_max_basket=a.covisit_max_basket,
            global_pop_df=gp, category_pop_df=cat,
        )
        names = source_names(sources)
        # The write is the action that truncates the lineage -- that, not the
        # loop itself, is what bounds plan size and peak shuffle.
        union = (
            union_daily_v2(sources, names, spine_type=a.spine_type)
            if a.ann_root is not None
            else union_daily(sources, names)
        )
        write_chunk(
            spark,
            a.out,
            ch,
            union,
            content_by_chunk[ch["chunk"]],
            extra={"ann_partitions": ann_meta},
        )
        events.unpersist()

    run_content = content_of(
        a,
        [manifests_by_day[day] for day in sorted(manifests_by_day)]
        if manifests_by_day
        else None,
    )
    run = PT.derive_run_meta(a.out, CHUNK_KEY, keys, extra={
        "day_range": [lo, hi], "chunk_weeks": a.chunk_weeks,
        "cadence": a.cadence, "phase": phase,
        "warm_up_days": CD.WARM_UP_DAYS, "args": run_content,
        "sources": list(SOURCE_ORDER),
    })
    print(f"TOTAL chunks {len(keys)}  rows {run['total_rows']}  "
          f"incomplete {len(run['incomplete'])}")
    if run["incomplete"]:
        raise SystemExit(f"chunks never completed: {run['incomplete'][:10]}")
    return run


if __name__ == "__main__":
    main()
