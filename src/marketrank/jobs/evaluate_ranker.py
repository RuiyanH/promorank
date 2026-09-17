"""One frozen test/holdout evaluation, with customer-cluster uncertainty."""
import argparse
import json
from pathlib import Path

import joblib
import numpy as np

from marketrank.evidence import sha256, write_json
from marketrank.jobs.train_ranker import load_frames
from marketrank.ranking.dataset import feature_matrix, prior_odds_correction, rrf_scores
from marketrank.ranking.freeze import validate_freeze
from marketrank.ranking.metrics import evaluate, paired_customer_bootstrap, promotion_gate
from marketrank.ranking.model import load_model, calibration_diagnostics


def run(root: Path):
    freeze = root / "evaluation-freeze.json"
    validate_freeze(freeze)
    output = root / "evaluation"
    if output.exists():
        raise ValueError("final evaluation output already exists; preserve the single evaluation")
    output.mkdir()
    write_json(output / "opened.json", {"evaluation_freeze_sha256": sha256(freeze),
        "policy": "single_frozen_evaluation_no_retuning"})
    model, manifest = load_model(root / "ranker")
    calibrator = joblib.load(root / "calibration/calibrator.joblib")
    results = {}
    for split in ("test", "holdout"):
        table, groups, provenance = load_frames(root / split, split)
        expected=manifest["frame_provenance"]["val_tune"][0]
        for field in ("bundle_manifest_sha256","candidate_config_id","builder_source_sha256"):
            if expected[field]!=provenance[0][field]:raise ValueError("evaluation pipeline differs from frozen model")
        x = feature_matrix(table)
        margin = model.predict(x, raw_score=True, num_threads=4)
        model_report, model_groups = evaluate(table, margin, groups)
        baseline, baseline_groups = evaluate(table, rrf_scores(table), groups)
        uncertainty = paired_customer_bootstrap(model_groups, baseline_groups)
        corrected = prior_odds_correction(model.predict(x, num_threads=4), manifest["negative_retention_probability"])
        labels = np.asarray(table["label"])
        result = {"model": model_report, "rrf": baseline, "bootstrap": uncertainty,
            "promotion_gate": promotion_gate(model_report, baseline, uncertainty, holdout=split=="holdout"),
            "calibration_before": calibration_diagnostics(labels, corrected),
            "calibration_after": calibration_diagnostics(labels, calibrator.predict(corrected)),
            "frame_provenance": provenance}
        write_json(output / f"{split}.json", result)
        results[split] = result
        print({"split": split, "model_ndcg": model_report["active_day_end_to_end_ndcg_at_12"],
            "rrf_ndcg": baseline["active_day_end_to_end_ndcg_at_12"], "gate": result["promotion_gate"]}, flush=True)
    report = {"schema_version": "ranker-evaluation.v2", "evaluation_freeze_sha256": sha256(freeze),
        "test": results["test"], "holdout": results["holdout"],
        "quality_gate_passed": all(v["promotion_gate"]["passed"] for v in results.values()),
        "release_status": "candidate", "independent_review": "pending", "human_usability": "pending"}
    write_json(output / "report.json", report)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args(argv).root)


if __name__ == "__main__":
    main()
