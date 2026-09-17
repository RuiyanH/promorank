"""Restricted analytical store over a verified Spark/Iceberg export.

Integer keys keep joins compact. Raw IDs and internal pseudonyms never become
browser artifacts; the replay release applies a separate release-scoped HMAC.
"""
from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import os
import secrets
import datetime as dt
from collections import deque
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from marketrank.evidence import sha256, sql_literal, write_json


class HistoricalStore:
    def __init__(self, root: Path, *, threads: int = 4, memory: str = "4GB"):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.db = duckdb.connect(str(root / "restricted.duckdb"))
        self.db.execute(f"SET threads={int(threads)}")
        self.db.execute(f"SET memory_limit={sql_literal(memory)}")
        self.db.execute(f"SET temp_directory={sql_literal(root / 'spill')}")
        self.db.execute("SET preserve_insertion_order=false")

    def initialize(self, source: Path, cohort: Path):
        if (self.root / "source.json").exists():
            existing = json.loads((self.root / "source.json").read_text())
            if existing["source_manifest_sha256"] != sha256(source / "manifest.json"):
                raise ValueError("store is bound to a different source snapshot")
            return
        manifest = json.loads((source / "manifest.json").read_text())
        for name, expected in manifest["files"].items():
            path = (source / name).resolve()
            if not path.is_relative_to(source.resolve()) or sha256(path) != expected:
                raise ValueError("source artifact checksum mismatch")
        db = self.db
        db.execute(f"CREATE VIEW source_tx AS SELECT * FROM read_parquet({sql_literal(source / 'transactions/*.parquet')})")
        db.execute(f"CREATE TABLE articles AS SELECT row_number() OVER (ORDER BY article_id)::INTEGER a, * FROM read_parquet({sql_literal(source / 'articles/*.parquet')})")
        db.execute("CREATE TABLE customers AS SELECT row_number() OVER (ORDER BY customer_id)::INTEGER c, customer_id FROM (SELECT DISTINCT customer_id FROM source_tx)")
        key_path = self.root / "internal-reference.key"
        if not key_path.exists():
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(secrets.token_bytes(32))
        key = key_path.read_bytes()
        mapping = [(c, "v2c_" + hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()[:24])
                   for c, raw in db.execute("SELECT c, customer_id FROM customers ORDER BY c").fetchall()]
        refs = pa.Table.from_pylist([{"c": c, "customer_key": value} for c, value in mapping])
        db.register("refs", refs)
        db.execute("CREATE TABLE customer_refs AS SELECT * FROM refs")
        db.unregister("refs")
        db.execute("CREATE TABLE tx AS SELECT c.c, a.a, datediff('day', DATE '2018-09-20', t.scoring_date)::INTEGER d, t.price::FLOAT price FROM source_tx t JOIN customers c USING(customer_id) JOIN articles a USING(article_id)")
        db.execute("CREATE TABLE first_seen AS SELECT a, min(d)::INTEGER first_day FROM tx GROUP BY a")
        db.execute(f"CREATE TABLE cohort AS SELECT c FROM customers JOIN read_parquet({sql_literal(cohort / '*.parquet')}) USING(customer_id)")
        count = db.execute("SELECT count(*) FROM cohort").fetchone()[0]
        if count != 20000:
            raise ValueError("fixed product cohort must contain 20000 customers")
        ids = db.execute("SELECT customer_id FROM customers JOIN cohort USING(c) ORDER BY customer_id").fetchnumpy()["customer_id"]
        cohort_hash = hashlib.sha256(("\n".join(ids) + "\n").encode()).hexdigest()
        db.execute("DROP VIEW source_tx")
        db.execute("CHECKPOINT")
        write_json(self.root / "source.json", {"source_manifest_sha256": sha256(source / "manifest.json"),
                   "through": manifest["through"], "transaction_snapshot": manifest["transaction_snapshot"],
                   "rows": db.execute("SELECT count(*) FROM tx").fetchone()[0], "cohort_rows": count,
                   "cohort_sorted_id_sha256": cohort_hash})

    def export_retrieval(self, output: Path, *, customer_limit: int = 100000, selection_customers: int = 10000):
        """Deterministic train-only customer sample; all fit positives retained.

        Recent sequence and counts are updated after every complete day, so no
        same-day positive can enter its own inputs. Cold-start rows use zeros.
        """
        if output.exists():
            raise ValueError("retrieval export already exists")
        output.mkdir(parents=True)
        db = self.db
        fit_end = (dt.date(2020, 6, 30) - dt.date(2018, 9, 20)).days
        select_end = fit_end + 14
        db.execute(f"CREATE OR REPLACE TEMP TABLE fit_customers AS SELECT c, row_number() OVER (ORDER BY c)::INTEGER customer_index FROM (SELECT c FROM tx JOIN customers USING(c) WHERE d <= {fit_end} GROUP BY c, customer_id ORDER BY sha256(customer_id), customer_id LIMIT {int(customer_limit)})")
        db.execute(f"CREATE OR REPLACE TEMP TABLE fit_articles AS SELECT a, row_number() OVER (ORDER BY article_id)::INTEGER article_index, article_id FROM articles JOIN first_seen USING(a) WHERE first_day <= {fit_end}")
        customer_rows = db.execute("SELECT customer_key, customer_index FROM fit_customers JOIN customer_refs USING(c) ORDER BY customer_index").fetchall()
        article_rows = db.execute("SELECT article_id, article_index FROM fit_articles ORDER BY article_index").fetchall()
        customers, articles = dict(customer_rows), dict(article_rows)
        write_json(output / "customer_vocabulary.json", customers)
        write_json(output / "article_vocabulary.json", articles)
        schema = pa.schema([("customer_index", pa.int64()), ("article_index", pa.int64()),
                            ("recent", pa.list_(pa.int64(), 10)), ("numeric", pa.list_(pa.float32(), 4))])
        writers = {name: pq.ParquetWriter(output / f"{name}.parquet", schema, compression="zstd") for name in ("fit", "select")}
        buffers = {"fit": [], "select": []}
        counts = {"fit": 0, "select": 0}
        # Unknown selection positives remain in the denominator as index zero;
        # only the fitted article vocabulary is searchable. Their transactions
        # still contribute to subsequent strictly-prior behavioral counts.
        query = f"SELECT customer_index, d, coalesce(article_index,0) article_index, count(*) n FROM tx JOIN fit_customers USING(c) LEFT JOIN fit_articles USING(a) WHERE d <= {select_end} GROUP BY customer_index,d,coalesce(article_index,0),a ORDER BY customer_index,d,a"
        reader = db.execute(query).fetch_record_batch(65536)
        rows = itertools.chain.from_iterable(batch.to_pylist() for batch in reader)
        try:
            for customer_index, customer_events in itertools.groupby(rows, key=lambda row: row["customer_index"]):
                history, recent, last_day = deque(), deque(maxlen=10), None
                for day, daily in itertools.groupby(customer_events, key=lambda row: row["d"]):
                    events = list(daily)
                    while history and history[0][0] < day - 90:
                        history.popleft()
                    numbers = [float(day - last_day) if last_day is not None else 999.,
                               *[float(sum(n for prior, n in history if prior >= day - width)) for width in (7, 30, 90)]]
                    split = "fit" if day <= fit_end else "select"
                    if day >= 90 and (split == "fit" or customer_index <= selection_customers):
                        for event in events:
                            buffers[split].append({"customer_index": customer_index, "article_index": event["article_index"],
                                                   "recent": [0] * (10 - len(recent)) + list(recent), "numeric": numbers})
                        if len(buffers[split]) >= 16384:
                            counts[split] += len(buffers[split])
                            writers[split].write_table(pa.Table.from_pylist(buffers[split], schema=schema))
                            buffers[split].clear()
                    for event in events:
                        recent.append(event["article_index"])
                    history.append((day, sum(event["n"] for event in events)))
                    last_day = day
            for name in writers:
                if buffers[name]:
                    counts[name] += len(buffers[name])
                    writers[name].write_table(pa.Table.from_pylist(buffers[name], schema=schema))
        finally:
            for writer in writers.values():
                writer.close()
        write_json(output / "manifest.json", {"counts": counts, "customer_limit": customer_limit,
                   "selection_customers": selection_customers, "population_rule": "sha256_raw_customer_id_among_retrieval_fit_customers",
                   "customer_vocabulary_sha256": sha256(output / "customer_vocabulary.json"),
                   "article_vocabulary_sha256": sha256(output / "article_vocabulary.json"),
                   "source_manifest_sha256": sha256(self.root / "source.json"),
                   "fit_sha256": sha256(output / "fit.parquet"), "select_sha256": sha256(output / "select.parquet")})
        print({"retrieval_export_rows": counts, "fit_customers": len(customers), "fit_articles": len(articles)}, flush=True)
        return customers, articles
