"""Immutable development-to-final-evaluation boundary."""
import json
from pathlib import Path

from marketrank.evidence import revision, sha256, write_json
from .dataset import BOUNDS, SEED


def create_freeze(root: Path, *, model: Path, calibrator: Path, source: Path) -> Path:
    path = root / "evaluation-freeze.json"
    if path.exists():
        raise ValueError("evaluation freeze already exists; final outcomes cannot justify retuning")
    model_meta = json.loads((model / "manifest.json").read_text())
    calibration = json.loads((calibrator / "manifest.json").read_text())
    if not model_meta.get("frozen") or calibration["model_manifest_sha256"] != sha256(model / "manifest.json"):
        raise ValueError("model/calibrator lineage must be complete before opening final outcomes")
    artifacts = [model / "manifest.json", model / model_meta["selected"]["model_file"],
                 calibrator / "manifest.json", calibrator / "calibrator.joblib"]
    from . import metrics, model as model_module
    code = [Path(metrics.__file__), Path(model_module.__file__), Path(__file__)]
    value = {"schema_version": "evaluation-freeze.v2", "code_revision": revision(),
        "artifacts": [{"path": str(p.resolve()), "sha256": sha256(p)} for p in artifacts],
        "evaluation_code": [{"path": str(p.resolve()), "sha256": sha256(p)} for p in code],
        "transaction_snapshot": json.loads((source / "manifest.json").read_text())["transaction_snapshot"],
        "splits": BOUNDS, "seed": SEED, "bootstrap_replicates": 2000,
        "policy": "open_final_outcomes_once_no_retuning",
        "test_relative_ndcg_min": .02, "test_absolute_ci_lower_gt": 0,
        "segment_absolute_drop_max": .005, "coverage_ratio_min": .9,
        "concentration_ratio_max": 1.1, "holdout_point_delta_gt": 0}
    write_json(path, value)
    validate_freeze(path)
    return path


def validate_freeze(path: Path) -> dict:
    value = json.loads(path.read_text())
    if value.get("schema_version") != "evaluation-freeze.v2" or value.get("policy") != "open_final_outcomes_once_no_retuning":
        raise ValueError("invalid evaluation freeze")
    if value.get("bootstrap_replicates") != 2000 or value.get("seed") != SEED:
        raise ValueError("evaluation rules differ from the frozen contract")
    for item in value["artifacts"] + value["evaluation_code"]:
        if sha256(Path(item["path"])) != item["sha256"]:
            raise ValueError("frozen model, calibrator or evaluation code changed")
    return value
