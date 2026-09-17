import numpy as np
import pyarrow as pa
import pytest

from marketrank.ranking.dataset import FEATURES, feature_matrix
from marketrank.ranking.model import train_ranker, load_model, calibration_diagnostics


def test_fixed_seed_training_reload_and_no_weights(tmp_path):
    rng=np.random.default_rng(18)
    rows=[]
    for c in range(20):
        for a in range(20):
            rows.append({**{f:float(rng.normal()) for f in FEATURES},
                "customer_id":str(c),"scoring_date":"2020-08-12","article_id":str(a),"label":int(a==c)})
    table=pa.Table.from_pylist(rows)
    groups=pa.Table.from_pylist([{"customer_id":str(c),"scoring_date":"2020-08-12","positive_count":1} for c in range(20)])
    grid=[{"configuration_id":"synthetic","num_leaves":7,"learning_rate":.05,"min_data_in_leaf":5}]
    manifest=train_ranker(table,table,groups,tmp_path/"one",threads=1,grid=grid,rounds=10,stopping_rounds=3)
    train_ranker(table,table,groups,tmp_path/"two",threads=1,grid=grid,rounds=10,stopping_rounds=3)
    one,_=load_model(tmp_path/"one")
    two,_=load_model(tmp_path/"two")
    assert manifest["sample_weights"] is False
    np.testing.assert_allclose(one.predict(feature_matrix(table),raw_score=True),two.predict(feature_matrix(table),raw_score=True),rtol=0,atol=1e-12)
    with (tmp_path/"one/synthetic.txt").open("a") as stream:
        stream.write("corrupt")
    with pytest.raises(ValueError):load_model(tmp_path/"one")


def test_calibration_thresholds_and_finite_values():
    y=np.array([1]*600+[0]*2400)
    report=calibration_diagnostics(y,np.full(3000,.2))
    assert report["brier"]==pytest.approx(.16)
    assert all(row["rows"]==200 for row in report["bins"])
    for labels,values in [(y[:2999],np.full(2999,.2)),(np.zeros(3000),np.zeros(3000)),(y,np.full(3000,np.nan))]:
        with pytest.raises(ValueError):calibration_diagnostics(labels,values)
