"""Build and verify browser-safe immutable DuckDB releases."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from datetime import date
from pathlib import Path

import duckdb

from marketrank.evidence import canonical, sha256, write_json
from marketrank.ranking.dataset import SOURCES

WARNING = "Historical replay from the static H&M Kaggle dataset. Scores order candidates only; they are not probabilities, confidence, current availability, or evidence of business uplift."
REF = re.compile(r"^v2c_[0-9a-f]{24}$")
ARTICLE = re.compile(r"^[0-9]{10}$")


def customer_ref(key: bytes, release_id: str, internal_id: str) -> str:
    if len(key) < 32:
        raise ValueError("release key must have at least 32 bytes")
    return "v2c_" + hmac.new(key, f"{release_id}\0{internal_id}".encode(), hashlib.sha256).hexdigest()[:24]


def validate_recommendations(value: dict) -> None:
    fields = {"schema_version", "release_id", "as_of", "ranking_mode", "score_semantics", "warning",
              "model_available_after", "calibrator_available_after", "customer_ref", "recommendations"}
    if set(value) != fields or value["schema_version"] != "workbench-api.v2":
        raise ValueError("recommendation schema mismatch")
    if value["ranking_mode"] != "trained_ranker" or value["score_semantics"] != "ordering_only":
        raise ValueError("invalid score semantics")
    if not REF.fullmatch(value["customer_ref"]):
        raise ValueError("invalid customer reference")
    if not date.fromisoformat(value["as_of"]) > max(date.fromisoformat(value["model_available_after"]), date.fromisoformat(value["calibrator_available_after"])):
        raise ValueError("replay precedes artifact availability")
    rows = value["recommendations"]
    if not 1 <= len(rows) <= 12 or len({row["article_id"] for row in rows}) != len(rows):
        raise ValueError("recommendations must contain 1..12 unique articles")
    ordering = []
    for position, row in enumerate(rows, 1):
        if set(row) != {"position", "article_id", "ordering_score", "source_evidence", "article_metadata"}:
            raise ValueError("unexpected recommendation fields")
        if row["position"] != position or not ARTICLE.fullmatch(row["article_id"]) or not math.isfinite(row["ordering_score"]):
            raise ValueError("invalid recommendation order/article/score")
        ordering.append((-row["ordering_score"], row["article_id"]))
        sources = row["source_evidence"]
        if not sources or len({source["source"] for source in sources}) != len(sources):
            raise ValueError("source evidence must be nonempty and unique")
        for source in sources:
            if set(source) != {"source", "display_name", "source_rank"} or source["source"] not in SOURCES:
                raise ValueError("invalid source evidence")
            expected = "embedding_retrieval" if source["source"] == "ann" else source["source"]
            if source["display_name"] != expected or type(source["source_rank"]) is not int or source["source_rank"] < 1:
                raise ValueError("invalid source rank/name")
        meta = row["article_metadata"]
        if set(meta) != {"product_type_name", "metadata_status"} or meta["metadata_status"] not in {"static_snapshot_attribute", "partial_static_snapshot"}:
            raise ValueError("invalid article metadata")
    if ordering != sorted(ordering):
        raise ValueError("ordering must be score descending/article ascending")


def logical_hash(db, table: str, order: str) -> str:
    digest = hashlib.sha256()
    # table/order are constants supplied by this module, never user input.
    cursor = db.execute(f"SELECT * FROM {table} ORDER BY {order}")
    while rows := cursor.fetchmany(4096):
        for row in rows:
            digest.update(canonical(row))
    return digest.hexdigest()


def build_release(output: Path, *, release_id: str, key: bytes, responses: list[dict],
                  quality: dict, provenance: dict, status: str = "candidate") -> dict:
    if output.exists() or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", release_id):
        raise ValueError("release output must be new and release ID must be safe")
    if status not in {"candidate", "verified"} or len(key) < 32 or not responses:
        raise ValueError("invalid release status/key/empty response set")
    output.mkdir(parents=True)
    db = duckdb.connect(str(output / "replay.duckdb"))
    db.execute("CREATE TABLE customers(customer_ref VARCHAR PRIMARY KEY, display_label VARCHAR UNIQUE NOT NULL)")
    db.execute("CREATE TABLE recommendations(customer_ref VARCHAR, as_of VARCHAR, payload VARCHAR NOT NULL, PRIMARY KEY(customer_ref,as_of))")
    raw_customers = sorted({value["customer_ref"] for value in responses})
    refs = {value: customer_ref(key, release_id, value) for value in raw_customers}
    dates = sorted({value["as_of"] for value in responses})
    db.executemany("INSERT INTO customers VALUES (?,?)", [(refs[value], f"Historical customer {index:05d}") for index, value in enumerate(raw_customers, 1)])
    sanitized = []
    for response in responses:
        value = {**response, "release_id": release_id, "customer_ref": refs[response["customer_ref"]]}
        validate_recommendations(value)
        sanitized.append((value["customer_ref"], value["as_of"], canonical(value).decode()))
    db.executemany("INSERT INTO recommendations VALUES (?,?,?)", sanitized)
    if len(sanitized) != len(raw_customers) * len(dates):
        raise ValueError("every cohort customer must have every approved replay date")
    hashes = {"customers": logical_hash(db, "customers", "customer_ref"),
              "recommendations": logical_hash(db, "recommendations", "customer_ref,as_of")}
    db.execute("CHECKPOINT")
    db.close()
    manifest = {"schema_version": "replay-release.v2", "release_id": release_id,
        "status": status, "data_mode": "historical_replay", "ranking_mode": "trained_ranker",
        "score_semantics": "ordering_only", "warning": WARNING, "dates": dates,
        "customer_count": len(raw_customers), "model_available_after": "2020-08-25",
        "calibrator_available_after": "2020-09-01", "database_sha256": sha256(output / "replay.duckdb"),
        "logical_sha256": hashes, "provenance": provenance, "quality": quality}
    write_json(output / "manifest.json", manifest)
    verify_release(output)
    return manifest


def verify_release(root: Path) -> dict:
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("schema_version") != "replay-release.v2" or sha256(root / "replay.duckdb") != manifest.get("database_sha256"):
        raise ValueError("release contract/checksum mismatch")
    with duckdb.connect(str(root / "replay.duckdb"), read_only=True) as db:
        if logical_hash(db, "customers", "customer_ref") != manifest["logical_sha256"]["customers"]:
            raise ValueError("customer logical checksum mismatch")
        if logical_hash(db, "recommendations", "customer_ref,as_of") != manifest["logical_sha256"]["recommendations"]:
            raise ValueError("recommendation logical checksum mismatch")
        counts = db.execute("SELECT count(*) FROM customers").fetchone()[0]
        if counts != manifest["customer_count"]:
            raise ValueError("release customer count mismatch")
    return manifest
