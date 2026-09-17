import datetime as dt

import numpy as np
import pyarrow.parquet as pq
import pytest
import torch

from marketrank.candidate_pipeline.analytical import DailyBuilder, EPOCH
from marketrank.candidate_pipeline.store import HistoricalStore
from marketrank.evidence import write_json
from marketrank.retrieval_v2.bundle import assemble_inference_bundle
from marketrank.retrieval_v2.model import PitSafeTwoTower, RetrievalTrainingResult


def fixture_builder(tmp_path):
    store = HistoricalStore(tmp_path / "store", threads=1, memory="512MB")
    db = store.db
    day = (dt.date(2020, 7, 15) - EPOCH).days
    db.execute("CREATE TABLE articles(a INTEGER, article_id VARCHAR, product_type_no INTEGER, product_type_name VARCHAR)")
    db.executemany("INSERT INTO articles VALUES (?,?,?,?)", [(i, f"{i:010}", i % 3, "Garment") for i in range(1, 61)])
    db.execute("CREATE TABLE customer_refs(c INTEGER, customer_key VARCHAR)")
    db.executemany("INSERT INTO customer_refs VALUES (?,?)", [(i, f"synthetic_customer_{i}") for i in range(1, 5)])
    db.execute("CREATE TABLE tx(c INTEGER,a INTEGER,d INTEGER,price FLOAT)")
    db.executemany("INSERT INTO tx VALUES (?,?,?,?)", [(c, a, day - (a % 10 + 1), .01*a) for c in range(1, 5) for a in range(1, 61)] + [(c, c, day, .05) for c in range(1, 5)])
    db.execute("CREATE TABLE first_seen AS SELECT a,min(d) first_day FROM tx GROUP BY a")
    db.execute("CREATE TABLE cohort AS SELECT c FROM customer_refs")
    write_json(store.root / "source.json", {"through": "2020-09-01"})
    torch.manual_seed(1)
    model = PitSafeTwoTower(4, 60, 4)
    articles = {f"{i:010}": i for i in range(1, 61)}
    customers = {f"synthetic_customer_{i}": i for i in range(1, 5)}
    with torch.no_grad():
        vectors = model.article(torch.arange(1, 61)).numpy()
    bundle = assemble_inference_bundle(tmp_path / "bundle", bundle_id="v2_pit_safe_test",
        data_mode="synthetic_fixture", training_result=RetrievalTrainingResult(model, {}, {}, "test"),
        customer_vocabulary=customers, article_vocabulary=articles, article_ids=list(articles), article_vectors=vectors,
        recent_k=10, code_revision="test", dependency_lock_sha256="0"*64)
    return DailyBuilder(store, bundle), day


def test_daily_pipeline_preserves_positives_sources_and_future_invariance(tmp_path):
    builder, day = fixture_builder(tmp_path)
    first = builder.build("2020-07-15", spine_type="active_day", output=tmp_path / "one", split="ranker_fit", pilot=True)
    assert len(first["source_rows"]) == 5
    frame = pq.read_table(tmp_path / "one/frame.parquet")
    assert sum(frame["label"].to_pylist()) == 4
    assert first["candidate_rows"] >= first["frame_rows"]
    # Same-day prices are outcomes, never features; future events must have no
    # effect on earlier candidate membership, query tensors, or feature values.
    builder.db.execute(f"UPDATE tx SET price=99 WHERE d={day}")
    builder.db.execute(f"INSERT INTO tx VALUES (1,60,{day+10},500)")
    builder.build("2020-07-15", spine_type="active_day", output=tmp_path / "two", split="ranker_fit", pilot=True)
    assert frame.equals(pq.read_table(tmp_path / "two/frame.parquet"))
    assert first == builder.build("2020-07-15", spine_type="active_day", output=tmp_path / "one", split="ranker_fit", pilot=True)
    with pytest.raises(ValueError):
        builder.build("2020-09-03", spine_type="active_day", output=tmp_path / "bad", split="test")
    builder.db.close()
