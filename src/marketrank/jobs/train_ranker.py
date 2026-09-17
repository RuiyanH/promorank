"""Train/select the frozen V2 LightGBM grid from verified daily frames."""
import argparse
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from marketrank.evidence import sha256, write_json
from marketrank.ranking.dataset import validate_frame_manifest
from marketrank.ranking.model import train_ranker


def load_frames(root: Path, split: str):
    frames, groups, provenance = [], [], []
    manifests = sorted(root.glob("*/manifest.json"))
    if not manifests:
        raise ValueError("no complete frame partitions")
    for path in manifests:
        manifest = json.loads(path.read_text())
        validate_frame_manifest(manifest, split)
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
