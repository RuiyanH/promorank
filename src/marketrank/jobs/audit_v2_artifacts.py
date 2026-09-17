"""Independently reconcile physical daily artifacts with their manifests."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow.compute as pc
import pyarrow.parquet as pq

from marketrank.contracts import SOURCES
from marketrank.evidence import canonical,sha256,write_json
from marketrank.ranking.dataset import BOUNDS,FEATURES


def audit_partition(path:Path) -> dict:
    manifest=json.loads((path/"manifest.json").read_text())
    expected={"frame.parquet","groups.parquet",*(f"{source}.parquet" for source in SOURCES)}
    if set(manifest["files"])!=expected or {p.name for p in path.glob("*.parquet")}!=expected:
        raise ValueError("daily partition must contain exactly five sources, frame and truth spine")
    if manifest["features"]!=list(FEATURES) or set(manifest["source_rows"])!=set(SOURCES):
        raise ValueError("feature/source contract mismatch")
    for name,digest in manifest["files"].items():
        if sha256(path/name)!=digest:raise ValueError("physical artifact checksum mismatch")
    for source in SOURCES:
        if pq.read_metadata(path/f"{source}.parquet").num_rows!=manifest["source_rows"][source]:
            raise ValueError("physical source row count mismatch")
    if pq.read_metadata(path/"groups.parquet").num_rows!=manifest["groups"]:
        raise ValueError("physical truth-spine count mismatch")
    labels=pq.read_table(path/"frame.parquet",columns=["label"])
    if len(labels)!=manifest["frame_rows"] or (pc.sum(labels["label"]).as_py() or 0)!=manifest["positive_rows"]:
        raise ValueError("physical sampled-frame counts or positive retention mismatch")
    if manifest["split"]!="ranker_fit" and manifest["frame_rows"]!=manifest["candidate_rows"]:
        raise ValueError("nontraining candidates may not be sampled")
    return {"manifest_sha256":sha256(path/"manifest.json"),"files":len(expected),
        **{key:manifest[key] for key in ("groups","candidate_rows","frame_rows","positive_rows","compressed_bytes")}}


def run(root:Path,output:Path,*,final:bool=False):
    names=["ranker_fit","val_tune","val_calib"]
    if final:
        from marketrank.ranking.freeze import validate_freeze
        validate_freeze(root/"evaluation-freeze.json")
        names += ["test","holdout","replay"]
    reports={};hashes=[]
    for name in names:
        if name=="replay":days={"2020-09-09","2020-09-16"}
        else:
            start,end=map(dt.date.fromisoformat,BOUNDS[name])
            days={(start+dt.timedelta(days=i)).isoformat() for i in range((end-start).days+1)}
        paths=sorted((root/name).glob("*/manifest.json"))
        if {p.parent.name for p in paths}!=days:raise ValueError("incomplete frozen partition range")
        parts=[audit_partition(p.parent) for p in paths]
        hashes.extend(p["manifest_sha256"] for p in parts)
        reports[name]={"partitions":len(parts),**{key:sum(p[key] for p in parts) for key in parts[0] if key!="manifest_sha256"}}
    report={"schema_version":"v2-artifact-audit.v2","status":"passed","splits":reports,
        "audited_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
        "ordered_manifest_set_sha256":hashlib.sha256(canonical(hashes)).hexdigest()}
    if final:
        with duckdb.connect(str(root/"store/restricted.duckdb"),read_only=True) as db:
            count=db.execute("SELECT count(*) FROM tx WHERE d BETWEEN datediff('day',DATE '2018-09-20',DATE '2020-09-02') AND datediff('day',DATE '2018-09-20',DATE '2020-09-08')").fetchone()[0]
        report["ope_env_read_audit"]={"usage":"context_only","global_context_rows":count,
            "target_scoring_range":["2020-09-09","2020-09-22"],"consumer":"DailyBuilder prior/article_stats/weekly_pairs",
            "source_record_sha256":sha256(root/"store/source.json"),"label_rows":0,"fit_rows":0,
            "note":"Daily manifests count personalized-spine context separately; this count covers global source history."}
    write_json(output,report)
    print(json.dumps(report,indent=2),flush=True)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--final",action="store_true",help="include frozen final splits, replay and context-only read audit")
    args=parser.parse_args();run(args.root,args.out,final=args.final)
