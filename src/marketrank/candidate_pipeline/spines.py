"""Distinct V2 Spark spine builders; neither silently becomes the other."""

from __future__ import annotations

from collections.abc import Iterable

from pyspark.sql import DataFrame, SparkSession, functions as F


class SpineError(ValueError):
    """A scoring spine contains outcomes, duplicates, or invalid date keys."""


def _require_columns(frame: DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise SpineError(f"{name} is missing columns {missing}")


def build_active_day_spine(active_customer_days: DataFrame) -> DataFrame:
    """Build one row per observed active customer/day, without outcome columns."""

    _require_columns(active_customer_days, {"customer_id", "day_index"}, "active-day input")
    if "spine_type" in active_customer_days.columns:
        invalid = active_customer_days.filter(F.col("spine_type") != "active_day").limit(1).count()
        if invalid:
            raise SpineError("active-day input contains a non-active spine_type")
    return (
        active_customer_days.select("customer_id", "day_index")
        .distinct()
        .withColumn("spine_type", F.lit("active_day"))
    )


def build_replay_day_spine(
    spark: SparkSession,
    cohort: DataFrame,
    day_indices: Iterable[int],
) -> DataFrame:
    """Cross the fixed cohort with approved dates; no outcomes are accepted."""

    _require_columns(cohort, {"customer_id"}, "replay cohort")
    forbidden = {"label", "truth_articles", "article_id", "price", "outcome"} & set(cohort.columns)
    if forbidden:
        raise SpineError(f"replay cohort contains outcome fields: {sorted(forbidden)}")
    days = list(day_indices)
    if not days or len(set(days)) != len(days):
        raise SpineError("replay dates must be a non-empty unique sequence")
    if any(isinstance(day, bool) or not isinstance(day, int) or day < 0 for day in days):
        raise SpineError("replay day_index values must be non-negative integers")
    day_frame = spark.createDataFrame([(day,) for day in days], "day_index int")
    return (
        cohort.select("customer_id")
        .distinct()
        .crossJoin(F.broadcast(day_frame))
        .withColumn("spine_type", F.lit("replay_day"))
    )
