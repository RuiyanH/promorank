"""Precompute the complete private 20,000-customer, two-anchor replay."""
import argparse
import json
import os
import re
import secrets
from pathlib import Path

import duckdb
import numpy as np
import pyarrow.parquet as pq

from marketrank.evidence import sha256
from marketrank.candidate_pipeline.guards import assert_large_output_path
from marketrank.ranking.dataset import FEATURES, SOURCES, feature_matrix
from marketrank.ranking.freeze import validate_freeze
from marketrank.ranking.model import load_model
from marketrank.replay.release import WARNING, build_release


def run(root: Path, output: Path, release_id: str, *, scratch_root: Path):
    root=assert_large_output_path(root,scratch_root)
    output=assert_large_output_path(output,scratch_root)
    if output.exists() or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}",release_id):
        raise ValueError("a new immutable output and safe release ID are required")
    validate_freeze(root/"evaluation-freeze.json")
    report=json.loads((root/"evaluation/report.json").read_text())
    if report["evaluation_freeze_sha256"]!=sha256(root/"evaluation-freeze.json"):
        raise ValueError("release evaluation lineage mismatch")
    model,meta=load_model(root/"ranker")
    with duckdb.connect(str(root/"store/restricted.duckdb"),read_only=True) as db:
        metadata=dict(db.execute("SELECT article_id,product_type_name FROM articles").fetchall())
    responses=[]
    frame_hashes=[]
    for day in ("2020-09-09","2020-09-16"):
        partition=root/"replay"/day
        manifest=json.loads((partition/"manifest.json").read_text())
        if manifest["spine_type"]!="replay_day" or manifest["groups"]!=20000 or manifest["features"]!=list(FEATURES):
            raise ValueError("replay requires the complete frozen cohort and feature contract")
        expected=meta["frame_provenance"]["val_tune"][0]
        for field in ("bundle_manifest_sha256","candidate_config_id","builder_source_sha256"):
            if manifest["identity"][field]!=expected[field]:raise ValueError("replay pipeline differs from frozen model")
        for name,digest in manifest["files"].items():
            if sha256(partition/name)!=digest:raise ValueError("replay input checksum mismatch")
        table=pq.read_table(partition/"frame.parquet")
        scores=model.predict(feature_matrix(table),raw_score=True,num_threads=4)
        customers=np.asarray(table["customer_id"])
        articles=np.asarray(table["article_id"])
        order=np.lexsort((articles,-scores,customers))
        sorted_customers=customers[order]
        starts=np.r_[0,np.flatnonzero(sorted_customers[1:]!=sorted_customers[:-1])+1]
        if len(starts)!=20000:raise ValueError("missing replay customers")
        ends=np.r_[starts[1:],len(order)]
        for lo,hi in zip(starts,ends,strict=True):
            top=order[lo:min(lo+12,hi)]
            if len(top)!=12:raise ValueError("full replay must provide twelve unique recommendations")
            rows=table.select(["article_id",*[f"{s}_rank" for s in SOURCES]]).take(top).to_pylist()
            recommendations=[]
            for position,(index,row) in enumerate(zip(top,rows,strict=True),1):
                name=metadata.get(row["article_id"])
                recommendations.append({"position":position,"article_id":row["article_id"],"ordering_score":float(scores[index]),
                    "source_evidence":[{"source":s,"display_name":"embedding_retrieval" if s=="ann" else s,
                        "source_rank":int(row[f"{s}_rank"])} for s in SOURCES if row[f"{s}_rank"] is not None],
                    "article_metadata":{"product_type_name":name,"metadata_status":"static_snapshot_attribute" if name else "partial_static_snapshot"}})
            responses.append({"schema_version":"workbench-api.v2","release_id":release_id,"as_of":day,
                "ranking_mode":"trained_ranker","score_semantics":"ordering_only","warning":WARNING,
                "model_available_after":meta["model_available_after"],"calibrator_available_after":"2020-09-01",
                "customer_ref":str(sorted_customers[lo]),"recommendations":recommendations})
        frame_hashes.append({"date":day,"manifest_sha256":sha256(partition/"manifest.json")})
        print({"replay_date":day,"customers":len(starts),"precomputed_recommendations":len(starts)*12},flush=True)
        del table,scores,customers,articles,order,sorted_customers
    key_path=root/"store"/f"{release_id}.key"
    if key_path.exists():
        if key_path.is_symlink() or key_path.stat().st_mode & 0o077:
            raise ValueError("release key must be a private regular file")
        key=key_path.read_bytes()
        if len(key)!=32:raise ValueError("invalid existing release key")
    else:
        descriptor=os.open(key_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        key=secrets.token_bytes(32)
        with os.fdopen(descriptor,"wb") as stream:stream.write(key);stream.flush();os.fsync(stream.fileno())
    result=build_release(output,release_id=release_id,key=key,responses=responses,quality=report,
        provenance={"data_mode":"historical_replay","retriever_manifest_sha256":sha256(root/"bundle/manifest.json"),
            "model_manifest_sha256":sha256(root/"ranker/manifest.json"),"calibrator_manifest_sha256":sha256(root/"calibration/manifest.json"),
            "evaluation_report_sha256":sha256(root/"evaluation/report.json"),"replay_frames":frame_hashes,
            "retriever_population":"100000 train-only sampled customers; all their fit positives",
            "cohort":"fixed 20000 historical evaluation customers"},status="candidate")
    print({"release_id":result["release_id"],"customers":result["customer_count"],"database_sha256":result["database_sha256"]},flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--release-id",required=True)
    p.add_argument("--scratch-root",type=Path,required=True)
    a=p.parse_args();run(a.root,a.out,a.release_id,scratch_root=a.scratch_root)
