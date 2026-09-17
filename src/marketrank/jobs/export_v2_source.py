"""Export a pinned Iceberg snapshot into restricted, phase-bounded Parquet.

Spark owns source truth. Downstream local/cluster jobs use this bounded export;
they never glob historical Iceberg data files (which would include stale rows).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from pyspark.sql import functions as F

from marketrank.candidate_pipeline.guards import assert_large_output_path
from marketrank.evidence import revision, sha256, write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--through", choices=["2020-09-01", "2020-09-15", "2020-09-22"], default="2020-09-01")
    parser.add_argument("--evaluation-freeze", type=Path)
    parser.add_argument("--driver-memory", default="4g")
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args(argv)
    out = assert_large_output_path(args.out, args.scratch_root)
    if out.exists():
        raise ValueError("source export output already exists")
    if args.through != "2020-09-01":
        if args.evaluation_freeze is None or not args.evaluation_freeze.is_file():
            raise ValueError("final outcomes require a frozen evaluation plan")
    from marketrank.spark import get_spark
    from marketrank.ingest import TRANSACTIONS_TABLE, ARTICLES_TABLE
    spark = get_spark("v2-source-export", driver_memory=args.driver_memory, master=f"local[{args.threads}]")
    try:
        snapshot = spark.sql(f"SELECT snapshot_id FROM {TRANSACTIONS_TABLE}.history ORDER BY made_current_at DESC LIMIT 1").first()[0]
        tx = spark.read.option("snapshot-id", str(snapshot)).table(TRANSACTIONS_TABLE)
        tx = tx.filter(F.col("t_dat") <= F.lit(args.through).cast("date")).select(
            "customer_id", "article_id", F.col("t_dat").alias("scoring_date"), "price")
        tx.repartition(16).write.mode("error").parquet(str(out / "transactions"))
        spark.table(ARTICLES_TABLE).select("article_id", "product_type_no", "product_type_name").coalesce(1).write.mode("error").parquet(str(out / "articles"))
        manifest = {"schema_version": "source-export.v2", "code_revision": revision(),
                    "transaction_snapshot": str(snapshot), "through": args.through,
                    "transaction_rows": spark.read.parquet(str(out / "transactions")).count(),
                    "restricted": True, "evaluation_freeze_sha256": sha256(args.evaluation_freeze) if args.evaluation_freeze else None,
                    "files": {str(path.relative_to(out)): sha256(path) for path in sorted(out.rglob("*.parquet"))}}
        write_json(out / "manifest.json", manifest)
        print({key: value for key, value in manifest.items() if key != "files"}, flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
