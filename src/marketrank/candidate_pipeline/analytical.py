"""Bounded daily candidate/frame execution over the pinned analytical export.

The source semantics mirror candidates_daily: full-history repurchase and
dominant category; 30-day popularity; weekly 30/20 co-visitation with 10 seeds.
DuckDB is an execution adapter, not a new retrieval configuration.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import torch

from marketrank.evidence import canonical, sha256, sql_literal, write_json
from marketrank.retrieval.inference_bundle import load_inference_bundle
from marketrank.retrieval_v2.exact import exact_daily_retrieval
from marketrank.retrieval_v2.model import PitSafeTwoTower
from marketrank.ranking.dataset import FEATURES, SOURCES, BOUNDS, SEED
from .store import HistoricalStore

EPOCH = dt.date(2018, 9, 20)


class DailyBuilder:
    def __init__(self, store: HistoricalStore, bundle_root: Path):
        self.store, self.db = store, store.db
        self.bundle = load_inference_bundle(bundle_root)
        self.root = bundle_root
        self.customers = json.loads(self.bundle.artifact_path("customer_vocabulary").read_text())
        self.articles = json.loads(self.bundle.artifact_path("article_vocabulary").read_text())
        self.model = PitSafeTwoTower(max(self.customers.values()), max(self.articles.values()), self.bundle.dimension)
        with np.load(self.bundle.artifact_path("model_weights"), allow_pickle=False) as arrays:
            self.model.load_state_dict({key: torch.from_numpy(arrays[key].copy()) for key in arrays.files})
        self.model.eval()
        with np.load(self.bundle.artifact_path("catalog_arrays"), allow_pickle=False) as arrays:
            self.article_ids = arrays["article_ids"].tolist()
            self.article_vectors = arrays["article_vectors"].copy()
        self.first_seen = {article: (EPOCH + dt.timedelta(days=day)).isoformat()
                           for article, day in self.db.execute("SELECT article_id, first_day FROM articles JOIN first_seen USING(a)").fetchall()
                           if article in self.articles}
        self.anchor = None

    def _covisit(self, day: int):
        anchor = day - ((day - 692) % 7)
        if self.anchor == anchor:
            return
        db = self.db
        db.execute(f"""CREATE OR REPLACE TEMP TABLE pair_events AS
            SELECT c,a,d FROM (SELECT DISTINCT c,a,d FROM tx WHERE d >= {anchor - 30} AND d < {anchor})
            QUALIFY row_number() OVER (PARTITION BY c ORDER BY d DESC,a) <= 20""")
        db.execute(f"""CREATE OR REPLACE TEMP TABLE pairs AS
            SELECT a,b,score FROM (SELECT x.a, y.a b, sum(pow(.5, ({anchor}-greatest(x.d,y.d))/30.)) score
            FROM pair_events x JOIN pair_events y ON x.c=y.c AND x.a<>y.a AND abs(x.d-y.d)<=7 GROUP BY x.a,y.a)
            QUALIFY row_number() OVER (PARTITION BY a ORDER BY score DESC,b) <= 20""")
        self.anchor = anchor

    def build(self, day_string: str, *, spine_type: str, output: Path, split: str | None = None,
              pilot: bool = False) -> dict:
        self.bundle.assert_scoring_date(day_string)
        day = (dt.date.fromisoformat(day_string) - EPOCH).days
        if spine_type not in {"active_day", "replay_day"}:
            raise ValueError("invalid spine type")
        source_manifest = json.loads((self.store.root / "source.json").read_text())
        if day_string > source_manifest["through"]:
            raise ValueError("source snapshot does not cover scoring date")
        if spine_type == "active_day":
            if split not in BOUNDS or not BOUNDS[split][0] <= day_string <= BOUNDS[split][1]:
                raise ValueError("active-day labels violate frozen chronology")
        elif day_string not in {"2020-09-09", "2020-09-16"}:
            raise ValueError("only approved post-calibration replay anchors are permitted")
        if pilot and (spine_type != "active_day" or not "2020-07-15" <= day_string <= "2020-07-21"):
            raise ValueError("pilot must be within the frozen train-only week")
        identity = {"scoring_date": day_string, "spine_type": spine_type, "split": split,
                    "bundle_manifest_sha256": sha256(self.root / "manifest.json"),
                    "source_manifest_sha256": sha256(self.store.root / "source.json"),
                    "candidate_config_id": "v2-five-source-30-40-40-40-50", "pilot": pilot}
        identity["builder_source_sha256"] = sha256(Path(__file__))
        if (output / "manifest.json").exists():
            manifest = json.loads((output / "manifest.json").read_text())
            if manifest["identity"] != identity:
                raise ValueError("existing partition has different inputs")
            for name, digest in manifest["files"].items():
                if sha256(output / name) != digest:
                    raise ValueError("existing partition checksum mismatch")
            return manifest
        if output.exists():
            raise ValueError("incomplete daily partition; preserve and move aside before retry")
        output.mkdir(parents=True)
        started = time.monotonic()
        db = self.db
        if spine_type == "active_day":
            cohort_join = "JOIN cohort USING(c)" if split != "ranker_fit" else ""
            db.execute(f"CREATE OR REPLACE TEMP TABLE spine AS SELECT c, count(DISTINCT a)::INTEGER positive_count FROM tx {cohort_join} WHERE d={day} GROUP BY c")
        else:
            db.execute("CREATE OR REPLACE TEMP TABLE spine AS SELECT c, 0::INTEGER positive_count FROM cohort")
        db.execute(f"CREATE OR REPLACE TEMP TABLE prior AS SELECT t.* FROM tx t JOIN spine USING(c) WHERE d < {day}")
        db.execute(f"""CREATE OR REPLACE TEMP TABLE customer_stats AS SELECT c,
            count(*) FILTER (WHERE d >= {day-7})::FLOAT purchase_count_7d,
            count(*) FILTER (WHERE d >= {day-30})::FLOAT purchase_count_30d,
            count(*) FILTER (WHERE d >= {day-90})::FLOAT purchase_count_90d,
            ({day}-max(d))::FLOAT days_since_last_purchase,
            avg(price) FILTER (WHERE d >= {day-90})::FLOAT customer_trailing_price FROM prior GROUP BY c""")
        db.execute(f"""CREATE OR REPLACE TEMP TABLE article_stats AS SELECT a,
            count(*) FILTER (WHERE d >= {day-7})::FLOAT article_count_7d,
            count(*) FILTER (WHERE d >= {day-30})::FLOAT article_count_30d,
            avg(price) FILTER (WHERE d >= {day-30})::FLOAT article_trailing_price
            FROM tx WHERE d < {day} GROUP BY a""")
        db.execute("""CREATE OR REPLACE TEMP TABLE recent AS SELECT c,a,d,
            row_number() OVER (PARTITION BY c ORDER BY d DESC,a) r FROM (SELECT DISTINCT c,a,d FROM prior)
            QUALIFY r<=10""")
        # Query tensor computation uses only pre-day events. Vocabulary misses
        # map to padding; arbitrary replay customers do not acquire learned IDs.
        rows = db.execute("""SELECT s.c, customer_key, coalesce(days_since_last_purchase,999),
            coalesce(purchase_count_7d,0),coalesce(purchase_count_30d,0),coalesce(purchase_count_90d,0)
            FROM spine s JOIN customer_refs USING(c) LEFT JOIN customer_stats USING(c) ORDER BY s.c""").fetchall()
        sequences = {}
        for c, article in db.execute("SELECT c,article_id FROM recent JOIN articles USING(a) ORDER BY c,r DESC").fetchall():
            sequences.setdefault(c, []).append(self.articles.get(article, 0))
        customer_keys = [row[1] for row in rows]
        queries = []
        with torch.no_grad():
            for start in range(0, len(rows), 2048):
                batch = rows[start:start+2048]
                recent = [[0] * (10-len(sequences.get(row[0], []))) + sequences.get(row[0], []) for row in batch]
                queries.append(self.model.customer(torch.tensor([self.customers.get(row[1], 0) for row in batch]),
                    torch.tensor(recent, dtype=torch.int64), torch.tensor([row[2:] for row in batch], dtype=torch.float32)).numpy())
        vectors = np.concatenate(queries) if queries else np.empty((0, self.bundle.dimension), dtype=np.float32)
        ann = exact_daily_retrieval(article_ids=self.article_ids, article_vectors=self.article_vectors,
            customer_ids=customer_keys, customer_vectors=vectors, article_first_seen=self.first_seen,
            scoring_date=day_string, day_index=day, depth=50, batch_size=128)
        lookup = {row[1]: row[0] for row in rows}
        ann_table = pa.Table.from_pylist([{"c": lookup[row["customer_id"]], "article_id": row["article_id"], "source_rank": row["source_rank"]} for row in ann],
                                       schema=pa.schema([("c", pa.int32()), ("article_id", pa.string()), ("source_rank", pa.int32())]))
        db.register("ann_input", ann_table)
        db.execute("CREATE OR REPLACE TEMP TABLE source_ann AS SELECT c,a,source_rank FROM ann_input JOIN articles USING(article_id)")
        db.unregister("ann_input")
        del ann, ann_table
        db.execute("""CREATE OR REPLACE TEMP TABLE source_repurchase AS SELECT c,a,
            row_number() OVER (PARTITION BY c ORDER BY latest DESC,n DESC,a)::INTEGER source_rank
            FROM (SELECT c,a,max(d) latest,count(*) n FROM prior GROUP BY c,a) QUALIFY source_rank<=30""")
        db.execute("""CREATE OR REPLACE TEMP TABLE global_pop AS SELECT a,
            row_number() OVER (ORDER BY article_count_30d DESC,a)::INTEGER source_rank
            FROM article_stats WHERE article_count_30d>0 QUALIFY source_rank<=40""")
        db.execute("CREATE OR REPLACE TEMP TABLE source_global_pop AS SELECT c,a,source_rank FROM spine CROSS JOIN global_pop")
        db.execute("""CREATE OR REPLACE TEMP TABLE dominant AS SELECT c,product_type_no FROM
            (SELECT c,product_type_no,count(*) n FROM prior JOIN articles USING(a) GROUP BY c,product_type_no)
            QUALIFY row_number() OVER (PARTITION BY c ORDER BY n DESC,product_type_no)<=1""")
        db.execute("""CREATE OR REPLACE TEMP TABLE category_pop AS SELECT a,product_type_no,
            row_number() OVER (PARTITION BY product_type_no ORDER BY article_count_30d DESC,a)::INTEGER source_rank
            FROM article_stats JOIN articles USING(a) WHERE article_count_30d>0 QUALIFY source_rank<=40""")
        db.execute("CREATE OR REPLACE TEMP TABLE source_category_pop AS SELECT c,a,source_rank FROM dominant JOIN category_pop USING(product_type_no)")
        self._covisit(day)
        db.execute(f"""CREATE OR REPLACE TEMP TABLE source_covisit AS SELECT c,a,
            row_number() OVER (PARTITION BY c ORDER BY score DESC,a)::INTEGER source_rank FROM
            (SELECT c,b a,sum(score/r) score FROM recent JOIN pairs USING(a) WHERE d >= {day-30} GROUP BY c,b)
            QUALIFY source_rank<=40""")
        source_counts = {}
        for name in SOURCES:
            source_counts[name] = db.execute(f"SELECT count(*) FROM source_{name}").fetchone()[0]
            db.execute(f"COPY (SELECT customer_key customer_id,{day} day_index, article_id, '{name}' AS \"source\", source_rank FROM source_{name} JOIN articles USING(a) JOIN customer_refs USING(c) ORDER BY c,source_rank) TO {sql_literal(output / (name + '.parquet'))} (FORMAT PARQUET, COMPRESSION ZSTD)")
        union_sql = " UNION ALL ".join(f"SELECT c,a,source_rank,'{name}' source_name FROM source_{name}" for name in SOURCES)
        ranks = ",".join(f"min(source_rank) FILTER (WHERE source_name='{name}')::INTEGER {name}_rank" for name in SOURCES)
        db.execute(f"CREATE OR REPLACE TEMP TABLE candidate_union AS SELECT c,a,{ranks},count(*)::INTEGER source_count FROM ({union_sql}) GROUP BY c,a")
        if db.execute(f"SELECT count(*) FROM candidate_union JOIN first_seen USING(a) WHERE first_day >= {day}").fetchone()[0]:
            raise ValueError("future article in candidate set")
        db.execute(f"""CREATE OR REPLACE TEMP TABLE cross_stats AS SELECT c,a,count(*) FILTER (WHERE d>={day-90})::FLOAT customer_article_count_90d,
            ({day}-max(d))::FLOAT customer_article_recency FROM prior GROUP BY c,a""")
        db.execute(f"""CREATE OR REPLACE TEMP TABLE category_stats AS SELECT c,product_type_no,count(*)::FLOAT customer_category_count_90d
            FROM prior JOIN articles USING(a) WHERE d>={day-90} GROUP BY c,product_type_no""")
        # Every feature expression refers to pre-day tables. Same-day tx supplies
        # labels only, and replay never joins outcome labels at all.
        label_join = f'LEFT JOIN (SELECT DISTINCT c,a,1 AS "label" FROM tx WHERE d={day}) labels USING(c,a)' if spine_type == "active_day" else ""
        label_expr = "coalesce(label,0)::INTEGER" if spine_type == "active_day" else "0::INTEGER"
        rank_columns = ",".join(f"u.{name}_rank" for name in SOURCES)
        db.execute(f"""CREATE OR REPLACE TEMP TABLE frame AS SELECT refs.customer_key customer_id,
            DATE {sql_literal(day_string)} scoring_date, a.article_id, {sql_literal(spine_type)} spine_type,
            {label_expr} AS "label", {rank_columns},u.source_count,
            coalesce(cs.purchase_count_7d,0)::FLOAT purchase_count_7d,coalesce(cs.purchase_count_30d,0)::FLOAT purchase_count_30d,
            coalesce(cs.purchase_count_90d,0)::FLOAT purchase_count_90d,coalesce(cs.days_since_last_purchase,999)::FLOAT days_since_last_purchase,
            ast.article_count_7d,ast.article_count_30d,ast.article_trailing_price,
            (ast.article_trailing_price IS NULL)::FLOAT article_trailing_price_missing,
            cs.customer_trailing_price,(cs.customer_trailing_price IS NULL)::FLOAT customer_trailing_price_missing,
            (ast.article_trailing_price/nullif(cs.customer_trailing_price,0))::FLOAT price_ratio,
            a.product_type_no::FLOAT product_type_no,
            coalesce(cat.customer_category_count_90d,0)::FLOAT customer_category_count_90d,
            coalesce(xs.customer_article_count_90d,0)::FLOAT customer_article_count_90d,
            coalesce(xs.customer_article_recency,999)::FLOAT customer_article_recency
            FROM candidate_union u JOIN articles a USING(a) JOIN customer_refs refs USING(c)
            LEFT JOIN customer_stats cs USING(c) LEFT JOIN article_stats ast USING(a)
            LEFT JOIN cross_stats xs USING(c,a) LEFT JOIN category_stats cat USING(c,product_type_no)
            {label_join}""")
        sampling = ""
        if split == "ranker_fit":
            # First 15 hexadecimal digits are exactly representable in a 64-bit
            # integer. The same key yields one stable Bernoulli decision.
            sampling = f"WHERE label=1 OR ('0x'||substr(sha256(cast({SEED} AS VARCHAR)||chr(0)||customer_id||chr(0)||cast(scoring_date AS VARCHAR)||chr(0)||article_id),1,15))::UBIGINT < {int(.05*16**15)}"
        db.execute(f"COPY (SELECT * FROM frame {sampling} ORDER BY customer_id,article_id) TO {sql_literal(output / 'frame.parquet')} (FORMAT PARQUET, COMPRESSION ZSTD)")
        db.execute(f"COPY (SELECT customer_key customer_id,DATE {sql_literal(day_string)} scoring_date,positive_count,CASE WHEN coalesce(purchase_count_90d,0)=0 THEN 'cold' WHEN purchase_count_90d<=5 THEN 'low' ELSE 'high' END activity_segment FROM spine JOIN customer_refs USING(c) LEFT JOIN customer_stats USING(c) ORDER BY customer_key) TO {sql_literal(output / 'groups.parquet')} (FORMAT PARQUET, COMPRESSION ZSTD)")
        total, positives = db.execute("SELECT count(*),sum(label) FROM frame").fetchone()
        written = pq.read_metadata(output / "frame.parquet").num_rows
        manifest = {"schema_version": "ranker-frame.v2", "identity": identity, "spine_type": spine_type,
                    "split": split, "features": list(FEATURES), "dates": [day_string],
                    "negative_retention_probability": .05 if split == "ranker_fit" else 1.,
                    "data_mode": "non_release_pilot" if pilot else "historical_offline",
                    "groups": len(rows), "candidate_rows": total, "frame_rows": written,
                    "positive_rows": int(positives or 0), "source_rows": source_counts,
                    "eligible_catalog_size": db.execute(f"SELECT count(*) FROM first_seen WHERE first_day<{day}").fetchone()[0],
                    "files": {p.name: sha256(p) for p in sorted(output.glob('*.parquet'))},
                    "compressed_bytes": sum(p.stat().st_size for p in output.glob('*.parquet')),
                    "wall_seconds": time.monotonic()-started,
                    "context_max_day": (EPOCH + dt.timedelta(days=day-1)).isoformat()}
        manifest["ope_env_policy"] = {"use": "antecedent_context_only" if day_string > "2020-09-08" else "not_read",
            "context_rows": db.execute("SELECT count(*) FROM prior WHERE d BETWEEN datediff('day', DATE '2018-09-20', DATE '2020-09-02') AND datediff('day', DATE '2018-09-20', DATE '2020-09-08')").fetchone()[0],
            "label_rows": 0, "fit_rows": 0}
        write_json(output / "manifest.json", manifest)
        print({key: manifest[key] for key in ("dates", "groups", "candidate_rows", "frame_rows", "wall_seconds", "compressed_bytes")}, flush=True)
        return manifest
