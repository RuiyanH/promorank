"""Train/select the frozen V2 LightGBM grid from verified daily frames."""
import argparse
import datetime as dt
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from marketrank.evidence import revision, sha256, write_json
from marketrank.ranking.dataset import BOUNDS, validate_frame_manifest
from marketrank.ranking.model import train_ranker


def load_frames(root: Path, split: str):
    frames, groups, provenance = [], [], []
    identities=set()
    manifests = sorted(root.glob("*/manifest.json"))
    if not manifests:
        raise ValueError("no complete frame partitions")
    start, end = map(dt.date.fromisoformat, BOUNDS[split])
    expected_dates = {(start + dt.timedelta(days=i)).isoformat() for i in range((end-start).days+1)}
    actual_dates = {path.parent.name for path in manifests}
    if actual_dates != expected_dates:
        raise ValueError("frame partitions must cover the complete frozen split")
    for path in manifests:
        manifest = json.loads(path.read_text())
        validate_frame_manifest(manifest, split)
        if manifest["dates"] != [path.parent.name] or manifest.get("data_mode") != "historical_offline":
            raise ValueError("partition date or release eligibility mismatch")
        for name in ("frame.parquet", "groups.parquet"):
            if sha256(path.parent / name) != manifest["files"][name]:
                raise ValueError("frame artifact checksum mismatch")
        frame=pq.read_table(path.parent / "frame.parquet")
        spine=pq.read_table(path.parent / "groups.parquet")
        if len(frame)!=manifest["frame_rows"] or len(spine)!=manifest["groups"] or sum(frame["label"].to_pylist())!=manifest["positive_rows"]:
            raise ValueError("physical frame counts or positive retention mismatch")
        if split!="ranker_fit" and len(frame)!=manifest["candidate_rows"]:
            raise ValueError("later splits must retain all candidates")
        identity=manifest["identity"]
        fields=("bundle_manifest_sha256","candidate_config_id","builder_source_sha256")
        identities.add(tuple(identity[f] for f in fields))
        frames.append(frame)
        groups.append(spine)
        provenance.append({"manifest_sha256": sha256(path), "date": manifest["dates"][0], **{f:identity[f] for f in fields}})
    if len(identities)!=1:
        raise ValueError("mixed candidate pipelines or retrievers within split")
    return pa.concat_tables(frames), pa.concat_tables(groups), provenance


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fit", type=Path, required=True)
    p.add_argument("--tune", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--threads", type=int, default=4)
    a = p.parse_args(argv)
    fit, _, fit_provenance = load_frames(a.fit, "ranker_fit")
    tune, groups, tune_provenance = load_frames(a.tune, "val_tune")
    for field in ("bundle_manifest_sha256","candidate_config_id","builder_source_sha256"):
        if fit_provenance[0][field]!=tune_provenance[0][field]:
            raise ValueError("fit and tune must use the same candidate pipeline")
    manifest = train_ranker(fit, tune, groups, a.out, threads=a.threads)
    from marketrank.ranking import model, metrics, dataset
    manifest["code_revision"]=revision()
    manifest["dependency_lock_sha256"]=sha256(Path("uv.lock"))
    manifest["implementation_sha256"]={Path(m.__file__).name:sha256(Path(m.__file__)) for m in (model,metrics,dataset)}
    manifest["frame_provenance"] = {"ranker_fit": fit_provenance, "val_tune": tune_provenance}
    write_json(a.out / "manifest.json", manifest)
    print({"selected": manifest["selected"]["configuration_id"], "metrics": manifest["selected"]["metrics"]}, flush=True)


if __name__ == "__main__":
    main()
