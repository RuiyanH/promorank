"""
The time-based split. Six disjoint slices, not four.

Three different things downstream each need data the others have not touched,
and a slice used twice tells you less than you think it does:

* `val_tune` vs `val_calib` -- fitting isotonic regression on the slice the
  ranker was early-stopped against makes measured ECE flatter itself. Cheap to
  avoid now, awkward to caveat later.
* `ope_env` -- week 8's reward model serves as ground truth, and if it is fit on
  the slice the ranker trained on, DM flatters itself and DR inherits the
  flattery through the residual term. Allocating the slice costs one line now;
  re-cutting data in week 8 means retraining the ranker to keep the boundaries
  honest.

`holdout` is the last 7 days so it mirrors the Kaggle test week's shape.

V2 narrows the old blanket `ope_env` prohibition. Its rows may be antecedent
context for a target date after the slice ends, but may never become labels,
fit/tune/calibration inputs, OPE evidence, or standalone reported metrics. The
permission check and audit record below make that distinction executable.
"""

from __future__ import annotations

from datetime import date

SPLITS: dict[str, tuple[str, str]] = {
    "train":     ("2018-09-20", "2020-08-11"),
    "val_tune":  ("2020-08-12", "2020-08-25"),
    "val_calib": ("2020-08-26", "2020-09-01"),
    "ope_env":   ("2020-09-02", "2020-09-08"),
    "test":      ("2020-09-09", "2020-09-15"),
    "holdout":   ("2020-09-16", "2020-09-22"),
}

# Consumers, so a later week cannot quietly borrow a slice.
CONSUMED_BY = {
    "train":     "two-tower (wk 3), ranker (wk 5)",
    "val_tune":  "ranker early stopping / hyperparameters (wk 5); retrieval recall (wk 3)",
    "val_calib": "isotonic calibration fit (wk 5.3) -- nothing else",
    "ope_env":   "reserved outcomes; context_only for target dates after 2020-09-08",
    "test":      "reported NDCG, AUC, revenue numbers",
    "holdout":   "local MAP@12 sanity check (wks 3-5)",
}

DATA_START = SPLITS["train"][0]
DATA_END = SPLITS["holdout"][1]

OPE_ENV_CONTEXT_USAGE = "context_only"
OPE_ENV_FORBIDDEN_USAGES = frozenset(
    {
        "label",
        "fit",
        "tune",
        "calibration",
        "ope",
        "standalone_metric",
    }
)


def bounds(name: str) -> tuple[str, str]:
    return SPLITS[name]


def sql_filter(name: str, col: str = "feature_date") -> str:
    lo, hi = SPLITS[name]
    return f"{col} between date'{lo}' and date'{hi}'"


def assert_slice_usage(
    source_slice: str,
    *,
    usage: str,
    target_date: str | None = None,
) -> None:
    """Reject an unauthorized use of a reserved temporal slice.

    Other slices retain their established consumers. `ope_env` is special:
    the only V2 exception is antecedent context for a scoring date strictly
    after the reserved slice. Callers must still persist an audit record.
    """

    if source_slice not in SPLITS:
        raise ValueError(f"unknown split: {source_slice}")
    if source_slice != "ope_env":
        return
    if usage != OPE_ENV_CONTEXT_USAGE:
        raise ValueError(
            "ope_env is reserved: only usage='context_only' is permitted; "
            f"got {usage!r}"
        )
    if target_date is None:
        raise ValueError("ope_env context usage requires a target_date")
    try:
        target = date.fromisoformat(target_date)
    except ValueError as exc:
        raise ValueError(f"invalid target_date: {target_date!r}") from exc
    reserved_end = date.fromisoformat(SPLITS["ope_env"][1])
    if target <= reserved_end:
        raise ValueError(
            "ope_env context is allowed only for target dates after "
            f"{reserved_end.isoformat()}; got {target.isoformat()}"
        )


def ope_env_context_audit(
    *,
    consumer_job: str,
    target_dates: list[str] | tuple[str, ...],
    row_count: int,
    input_snapshot: str,
) -> dict[str, object]:
    """Return the manifest record required for an allowed context-only read."""

    if not consumer_job.strip():
        raise ValueError("consumer_job is required")
    if not input_snapshot.strip():
        raise ValueError("input_snapshot is required")
    if row_count < 0:
        raise ValueError("row_count must be nonnegative")
    normalized = sorted(set(target_dates))
    if not normalized:
        raise ValueError("at least one target date is required")
    for scoring_date in normalized:
        assert_slice_usage(
            "ope_env", usage=OPE_ENV_CONTEXT_USAGE, target_date=scoring_date
        )
    return {
        "source_slice": "ope_env",
        "usage": OPE_ENV_CONTEXT_USAGE,
        "consumer_job": consumer_job,
        "target_dates": normalized,
        "row_count": row_count,
        "input_snapshot": input_snapshot,
    }
