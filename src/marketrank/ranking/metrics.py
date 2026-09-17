"""Ranking metrics preserve unreachable groups and bootstrap whole customers."""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import pyarrow as pa

from .dataset import SEED


def evaluate(table: pa.Table, scores: np.ndarray, groups: pa.Table, k: int = 12) -> tuple[dict, list[dict]]:
    """Groups contain ALL active customer-days and their distinct positive counts.

    End-to-end ideal DCG uses all purchases, including purchases retrieval missed.
    Conditional ideal DCG uses reachable positives and excludes zero-reach groups.
    """
    if len(table) != len(scores) or not np.isfinite(scores).all():
        raise ValueError("one finite score per candidate is required")
    by_group = defaultdict(list)
    data = table.select(["customer_id", "scoring_date", "article_id", "label"]).to_pylist()
    for row, score in zip(data, scores, strict=True):
        by_group[(row["customer_id"], str(row["scoring_date"]))].append(
            (float(score), row["article_id"], int(row["label"]))
        )
    discounts = 1 / np.log2(np.arange(2, k + 2))
    group_rows = []
    selected = []
    all_articles = set(table["article_id"].to_pylist())
    seen = set()
    for group in groups.to_pylist():
        key = (group["customer_id"], str(group["scoring_date"]))
        if key in seen or int(group["positive_count"]) < 1:
            raise ValueError("groups must be unique with positive truth counts")
        seen.add(key)
        candidates = sorted(by_group.pop(key, []), key=lambda row: (-row[0], row[1]))
        if len({row[1] for row in candidates}) != len(candidates):
            raise ValueError("duplicate candidate grain")
        positive_count = int(group["positive_count"])
        reachable = sum(row[2] for row in candidates)
        if reachable > positive_count:
            raise ValueError("reachable positives exceed the truth denominator")
        top = candidates[:k]
        hits = np.asarray([row[2] for row in top], dtype=float)
        dcg = float(hits @ discounts[:len(hits)])
        ap_numerator = float(np.sum(np.cumsum(hits) / np.arange(1, len(hits) + 1) * hits))
        selected.extend(row[1] for row in top)
        group_rows.append({
            "customer_id": key[0], "scoring_date": key[1],
            "positive_count": positive_count, "reachable_positives": reachable,
            "candidate_count": len(candidates),
            "activity_segment": group.get("activity_segment", "unknown"),
            "ndcg": dcg / float(discounts[:min(k, positive_count)].sum()),
            "conditional_ndcg": dcg / float(discounts[:min(k, reachable)].sum()) if reachable else None,
            "map": ap_numerator / min(k, positive_count),
            "recall": float(hits.sum()) / positive_count,
            "precision": float(hits.sum()) / k,
        })
    if by_group or not group_rows:
        raise ValueError("candidate groups must belong to the complete nonempty truth spine")
    reachable_groups = [row for row in group_rows if row["reachable_positives"]]
    _, counts = np.unique(selected, return_counts=True)
    # Denominator is the eligible candidate catalog, shared between model/RRF.
    concentration_n = max(1, int(np.ceil(len(all_articles) * .01)))
    report = {
        "spine_type": "active_day", "groups": len(group_rows),
        "reachable_groups": len(reachable_groups), "customers": len({r['customer_id'] for r in group_rows}),
        "candidate_rows": len(table), "positive_count": sum(r["positive_count"] for r in group_rows),
        "reachable_positives": sum(r["reachable_positives"] for r in group_rows),
        "active_day_candidate_conditional_ndcg_at_12": float(np.mean([r["conditional_ndcg"] for r in reachable_groups])) if reachable_groups else 0.0,
        "catalog_coverage": len(set(selected)) / max(1, len(all_articles)),
        "top_one_percent_concentration": float(np.sort(counts)[-concentration_n:].sum()) / max(1, len(selected)),
        "coverage_denominator": "union_candidate_catalog",
    }
    for metric in ("ndcg", "map", "recall", "precision"):
        report[f"active_day_end_to_end_{metric}_at_12"] = float(np.mean([r[metric] for r in group_rows]))
    report["candidate_recall_ceiling"] = report["reachable_positives"] / report["positive_count"]
    report["activity_segments"] = {
        segment: {"groups": sum(r["activity_segment"] == segment for r in group_rows),
                  "ndcg_at_12": float(np.mean([r["ndcg"] for r in group_rows if r["activity_segment"] == segment]))}
        for segment in sorted({r["activity_segment"] for r in group_rows})
    }
    return report, group_rows


def paired_customer_bootstrap(model: list[dict], baseline: list[dict], replicates: int = 2000) -> dict:
    if [(r['customer_id'], r['scoring_date']) for r in model] != [(r['customer_id'], r['scoring_date']) for r in baseline]:
        raise ValueError("paired evaluation must have identical ordered groups")
    sums = defaultdict(lambda: [0., 0])
    for left, right in zip(model, baseline, strict=True):
        pair = sums[left["customer_id"]]
        pair[0] += left["ndcg"] - right["ndcg"]
        pair[1] += 1
    if len(sums) < 2 or replicates < 1:
        raise ValueError("bootstrap requires at least two customer clusters")
    array = np.asarray([sums[key] for key in sorted(sums)])
    rng = np.random.default_rng(SEED)
    deltas = np.empty(replicates)
    for index in range(replicates):
        sample = array[rng.integers(0, len(array), size=len(array))]
        deltas[index] = sample[:, 0].sum() / sample[:, 1].sum()
    return {"method": "paired_customer_cluster_percentile", "seed": SEED,
            "replicates": replicates, "clusters": len(array),
            "point_delta": float(array[:, 0].sum() / array[:, 1].sum()),
            "ci95": np.quantile(deltas, [.025, .975]).tolist()}


def promotion_gate(model: dict, baseline: dict, bootstrap: dict, *, holdout: bool = False) -> dict:
    metric = "active_day_end_to_end_ndcg_at_12"
    delta = model[metric] - baseline[metric]
    reasons = []
    if holdout:
        if delta <= 0:
            reasons.append("holdout_ndcg_not_positive")
    elif baseline[metric] <= 0 or delta / baseline[metric] < .02 or bootstrap["ci95"][0] <= 0:
        reasons.append("test_improvement_or_confidence_gate")
    if model["catalog_coverage"] < .9 * baseline["catalog_coverage"]:
        reasons.append("catalog_coverage")
    if model["top_one_percent_concentration"] > 1.1 * baseline["top_one_percent_concentration"]:
        reasons.append("article_concentration")
    if set(model["activity_segments"]) != set(baseline["activity_segments"]):
        raise ValueError("segment populations differ")
    for segment, result in model["activity_segments"].items():
        if result["ndcg_at_12"] < baseline["activity_segments"][segment]["ndcg_at_12"] - .005:
            reasons.append(f"segment:{segment}")
    return {"passed": not reasons, "failed_rules": reasons, "absolute_ndcg_delta": delta}
