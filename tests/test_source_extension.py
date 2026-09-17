import datetime as dt
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from marketrank.candidate_pipeline.store import HistoricalStore
from marketrank.evidence import sha256,write_json


def test_extension_preserves_ids_is_transactional_and_recovers_sidecar(tmp_path,monkeypatch):
    from marketrank.ranking import freeze as freeze_module
    monkeypatch.setattr(freeze_module,"validate_freeze",lambda path:{})
    freeze=tmp_path/"freeze.json";write_json(freeze,{"synthetic":True})
    store=HistoricalStore(tmp_path/"store",threads=1,memory="512MB")
    store.db.execute("CREATE TABLE customers(c INTEGER,customer_id VARCHAR)")
    store.db.execute("INSERT INTO customers VALUES (1,'existing')")
    store.db.execute("CREATE TABLE customer_refs(c INTEGER,customer_key VARCHAR)")
    store.db.execute("INSERT INTO customer_refs VALUES (1,'stable_reference')")
    store.db.execute("CREATE TABLE articles(a INTEGER,article_id VARCHAR)")
    store.db.execute("INSERT INTO articles VALUES (1,'0000000001')")
    store.db.execute("CREATE TABLE tx(c INTEGER,a INTEGER,d INTEGER,price FLOAT)")
    store.db.execute("INSERT INTO tx VALUES (1,1,712,.1)")
    store.db.execute("CREATE TABLE first_seen AS SELECT a,min(d) first_day FROM tx GROUP BY a")
    (store.root/"internal-reference.key").write_bytes(b"k"*32)
    previous={"source_manifest_sha256":"old","through":"2020-09-01","transaction_snapshot":"1","rows":1}
    write_json(store.root/"source.json",previous)
    source=tmp_path/"source";(source/"transactions").mkdir(parents=True)
    path=source/"transactions/part.parquet"
    pq.write_table(pa.Table.from_pylist([
        {"customer_id":"existing","article_id":"0000000001","scoring_date":dt.date(2020,9,1),"price":.1},
        {"customer_id":"new","article_id":"0000000001","scoring_date":dt.date(2020,9,9),"price":.2}]),path)
    manifest={"transaction_snapshot":"1","through":"2020-09-22","evaluation_freeze_sha256":sha256(freeze),
        "transaction_rows":3,"files":{"transactions/part.parquet":sha256(path)}}
    write_json(source/"manifest.json",manifest)
    with pytest.raises(ValueError,match="counts"):store.extend_source(source,freeze)
    assert store.db.execute("SELECT count(*) FROM tx").fetchone()[0]==1
    assert store.db.execute("SELECT count(*) FROM customers").fetchone()[0]==1
    write_json(source/"manifest.json",{**manifest,"transaction_rows":2})
    store.extend_source(source,freeze)
    assert store.db.execute("SELECT customer_key FROM customer_refs WHERE c=1").fetchone()[0]=="stable_reference"
    assert store.db.execute("SELECT c FROM customers WHERE customer_id='new'").fetchone()[0]==2
    store.db.close()
    write_json(store.root/"source.json",previous)
    recovered=HistoricalStore(store.root,threads=1,memory="512MB")
    assert json.loads((store.root/"source.json").read_text())["through"]=="2020-09-22"
    recovered.extend_source(source,freeze)
    assert recovered.db.execute("SELECT count(*) FROM tx").fetchone()[0]==2
    recovered.db.close()
