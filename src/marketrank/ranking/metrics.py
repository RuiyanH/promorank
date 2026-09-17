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
    # Encode repeated strings once, rather than creating millions of Python
    # dictionaries. The sort key remains group, score descending, article ID.
    customer_dictionary=table["customer_id"].combine_chunks().dictionary_encode()
    date_dictionary=table["scoring_date"].combine_chunks().dictionary_encode()
    article_dictionary=table["article_id"].combine_chunks().dictionary_encode()
    customer_index={value:i for i,value in enumerate(customer_dictionary.dictionary.to_pylist())}
    date_index={str(value):i for i,value in enumerate(date_dictionary.dictionary.to_pylist())}
    all_articles=article_dictionary.dictionary.to_pylist()
    article_ordinals=np.argsort(np.argsort(all_articles))
    article_codes=np.asarray(article_dictionary.indices)
    group_codes=np.asarray(customer_dictionary.indices,dtype=np.int64)*max(1,len(date_index))+np.asarray(date_dictionary.indices)
    labels=np.asarray(table["label"])
    if not np.isin(labels,[0,1]).all():raise ValueError("candidate labels must be binary")
    order=np.lexsort((article_ordinals[article_codes],-np.asarray(scores),group_codes))
    boundaries=np.r_[0,np.flatnonzero(group_codes[order][1:]!=group_codes[order][:-1])+1,len(order)]
    by_group={int(group_codes[order[lo]]):(lo,hi) for lo,hi in zip(boundaries[:-1],boundaries[1:],strict=True) if hi>lo}
    discounts = 1 / np.log2(np.arange(2, k + 2))
    group_rows = []
    selected = []
    seen = set()
    for group in groups.to_pylist():
        key = (group["customer_id"], str(group["scoring_date"]))
        if key in seen or int(group["positive_count"]) < 1:
            raise ValueError("groups must be unique with positive truth counts")
        seen.add(key)
        code=customer_index.get(key[0],-1)*max(1,len(date_index))+date_index.get(key[1],-1)
        lo,hi=by_group.pop(code,(0,0)) if key[0] in customer_index and key[1] in date_index else (0,0)
        candidates=order[lo:hi]
        if len(np.unique(article_codes[candidates])) != len(candidates):
            raise ValueError("duplicate candidate grain")
        positive_count = int(group["positive_count"])
        reachable = int(labels[candidates].sum())
        if reachable > positive_count:
            raise ValueError("reachable positives exceed the truth denominator")
        top = candidates[:k]
        hits = labels[top].astype(float)
        dcg = float(hits @ discounts[:len(hits)])
        ap_numerator = float(np.sum(np.cumsum(hits) / np.arange(1, len(hits) + 1) * hits))
        selected.extend(article_codes[top].tolist())
        group_rows.append({
            "customer_id": key[0], "scoring_date": key[1],
            "positive_count": positive_count, "reachable_positives": reachable,
            "candidate_count": len(candidates),
            "activity_segment": group.get("activity_segment", "unknown"),
            "ndcg": dcg / float(discounts[:min(k, positive_count)].sum()),
            "conditional_ndcg": dcg / float(discounts[:min(k, reachable)].sum()) if reachable else None,
            "conditional_map": ap_numerator / min(k, reachable) if reachable else None,
            "conditional_recall": float(hits.sum()) / reachable if reachable else None,
            "conditional_precision": float(hits.sum()) / k if reachable else None,
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
        report[f"active_day_candidate_conditional_{metric}_at_12"] = float(np.mean([r[f"conditional_{metric}"] for r in reachable_groups])) if reachable_groups else 0.
    report["candidate_recall_ceiling"] = report["reachable_positives"] / report["positive_count"]
    report["activity_segments"] = {
        segment: {"groups": sum(r["activity_segment"] == segment for r in group_rows),
                  "ndcg_at_12": float(np.mean([r["ndcg"] for r in group_rows if r["activity_segment"] == segment]))}
        for segment in sorted({r["activity_segment"] for r in group_rows})
    }
    report["candidate_count_segments"] = {
        name: {"groups": len(subset), "ndcg_at_12": float(np.mean([r["ndcg"] for r in subset]))}
        for name, lo, hi in (("0_to_99",0,99),("100_to_149",100,149),("150_plus",150,10000))
        if (subset := [r for r in group_rows if lo <= r["candidate_count"] <= hi])
    }
    from .dataset import SOURCES
    if all(f"{source}_rank" in table.column_names for source in SOURCES):
        labels = np.asarray(table["label"])
        report["source_contribution"] = {
            source: {"candidate_memberships": int(np.isfinite(ranks).sum()),
                     "reachable_positive_memberships": int(labels[np.isfinite(ranks)].sum())}
            for source in SOURCES
            for ranks in [table[f"{source}_rank"].cast(pa.float64()).to_numpy()]
        }
        report["source_contribution_note"] = "Overlapping memberships; source counts are not additive or causal attribution."
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
