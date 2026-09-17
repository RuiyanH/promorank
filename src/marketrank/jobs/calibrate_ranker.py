import argparse
import json
from pathlib import Path
from marketrank.jobs.train_ranker import load_frames
from marketrank.ranking.model import fit_calibrator
from marketrank.evidence import write_json


def main(argv=None):
    p = argparse.ArgumentParser(description="Fit offline V2 calibration on unsampled val_calib only")
    p.add_argument("--frames", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    table, _, provenance = load_frames(a.frames, "val_calib")
    model_meta=json.loads((a.model/"manifest.json").read_text())
    expected=model_meta["frame_provenance"]["val_tune"][0]
    for field in ("bundle_manifest_sha256","candidate_config_id","builder_source_sha256"):
        if expected[field]!=provenance[0][field]:raise ValueError("calibration pipeline differs from selected model")
    result = fit_calibrator(a.model, table, a.out)
    result["frame_provenance"] = provenance
    write_json(a.out / "manifest.json", result)


if __name__ == "__main__":
    main()
