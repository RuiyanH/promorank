"""Train/select the frozen V2 LightGBM grid from verified daily frames."""
import argparse
import datetime as dt
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from marketrank.evidence import sha256, write_json
from marketrank.ranking.dataset import BOUNDS, validate_frame_manifest
from marketrank.ranking.model import train_ranker


def load_frames(root: Path, split: str):
    frames, groups, provenance = [], [], []
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
        frames.append(pq.read_table(path.parent / "frame.parquet"))
        groups.append(pq.read_table(path.parent / "groups.parquet"))
        provenance.append({"manifest_sha256": sha256(path), "date": manifest["dates"][0]})
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
    manifest = train_ranker(fit, tune, groups, a.out, threads=a.threads)
    manifest["frame_provenance"] = {"ranker_fit": fit_provenance, "val_tune": tune_provenance}
    write_json(a.out / "manifest.json", manifest)
    print({"selected": manifest["selected"]["configuration_id"], "metrics": manifest["selected"]["metrics"]}, flush=True)


if __name__ == "__main__":
    main()
