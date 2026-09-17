import numpy as np
import pyarrow as pa
import pytest

from marketrank.ranking.dataset import prior_odds_correction, keep_negative, validate_split_dates
from marketrank.ranking.metrics import evaluate, paired_customer_bootstrap, promotion_gate


def test_unreachable_purchases_and_groups_remain_in_denominator():
    table = pa.Table.from_pylist([
        {"customer_id": "a", "scoring_date": "2020-08-12", "article_id": "x", "label": 1},
        {"customer_id": "a", "scoring_date": "2020-08-12", "article_id": "z", "label": 0},
    ])
    groups = pa.Table.from_pylist([
        {"customer_id": "a", "scoring_date": "2020-08-12", "positive_count": 2},
        {"customer_id": "b", "scoring_date": "2020-08-12", "positive_count": 1},
    ])
    report, rows = evaluate(table, np.array([2., 1.]), groups)
    assert report["groups"] == 2 and report["reachable_groups"] == 1
    assert report["candidate_recall_ceiling"] == pytest.approx(1 / 3)
    assert report["active_day_end_to_end_ndcg_at_12"] == pytest.approx(.5 / (1 + 1 / np.log2(3)))
    assert report["active_day_candidate_conditional_ndcg_at_12"] == 1
    assert rows[1]["ndcg"] == 0


def test_correction_once_and_temporal_policy():
    assert prior_odds_correction([.5])[0] == pytest.approx(.05 / 1.05)
    with pytest.raises(ValueError):
        prior_odds_correction([float("nan")])
    with pytest.raises(ValueError):
        validate_split_dates("ranker_fit", ["2020-08-12"])
    with pytest.raises(ValueError):
        validate_split_dates("ope_env", ["2020-09-03"])
    sample = [keep_negative("a", "2020-07-15", str(i)) for i in range(10000)]
    assert 400 < sum(sample) < 600
    assert sample == [keep_negative("a", "2020-07-15", str(i)) for i in range(10000)]


def test_bootstrap_pairs_all_days_of_a_customer():
    model = [{"customer_id": c, "scoring_date": d, "ndcg": .5}
             for c, d in [("a", "1"), ("a", "2"), ("b", "1")]]
    base = [{**row, "ndcg": .25} for row in model]
    result = paired_customer_bootstrap(model, base, replicates=50)
    assert result["clusters"] == 2
    assert result["ci95"] == [.25, .25]
    with pytest.raises(ValueError):
        paired_customer_bootstrap(model, base[::-1])


def test_vectorized_ranking_uses_article_ties_and_rejects_duplicate_grain():
    table=pa.Table.from_pylist([
        {"customer_id":"c","scoring_date":"2020-08-12","article_id":"z","label":0},
        {"customer_id":"c","scoring_date":"2020-08-12","article_id":"a","label":1}])
    groups=pa.Table.from_pylist([{"customer_id":"c","scoring_date":"2020-08-12","positive_count":1}])
    report,_=evaluate(table,np.ones(2),groups)
    assert report["active_day_end_to_end_ndcg_at_12"]==1
    with pytest.raises(ValueError,match="duplicate candidate"):
        evaluate(pa.concat_tables([table,table]),np.ones(4),groups)


def test_promotion_rejects_quality_or_segment_regression():
    base = {"active_day_end_to_end_ndcg_at_12": .1, "catalog_coverage": .2,
            "top_one_percent_concentration": .5, "activity_segments": {"low": {"ndcg_at_12": .1}}}
    improved = {**base, "active_day_end_to_end_ndcg_at_12": .11}
    assert promotion_gate(improved, base, {"ci95": [.001, .02]})["passed"]
    improved["activity_segments"] = {"low": {"ndcg_at_12": .09}}
    assert not promotion_gate(improved, base, {"ci95": [.001, .02]})["passed"]
