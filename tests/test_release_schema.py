from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator, FormatChecker
import pytest

from marketrank.release import REQUIRED_SOURCES
from test_release_core import build_synthetic_release


ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "contracts/workbench-release.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def test_synthetic_release_validates_against_schema() -> None:
    VALIDATOR.validate(build_synthetic_release())


def test_schema_rejects_unexpected_or_unsupported_fields() -> None:
    release = deepcopy(build_synthetic_release())
    release["customers"][0]["recommendations"][0]["price"] = 19.99
    with pytest.raises(Exception):
        VALIDATOR.validate(release)


def test_schema_requires_each_source_metric_exactly_once() -> None:
    release = deepcopy(build_synthetic_release())
    release["diagnostics"]["source_metrics"][4]["source"] = "ann"
    with pytest.raises(Exception):
        VALIDATOR.validate(release)


def test_real_demo_release_validates_and_reconciles() -> None:
    release_path = ROOT / "workbench/public/data/demo-release.json"
    if not release_path.exists():
        pytest.skip("real demo release has not been generated")
    release = json.loads(release_path.read_text())
    ceiling = json.loads((ROOT / "artifacts/candidates/ceiling.json").read_text())
    VALIDATOR.validate(release)
    assert release["diagnostics"]["candidate_recall_ceiling"] == ceiling["ceiling"]["recall_ceiling"]
    assert release["diagnostics"]["mean_candidate_count"] == ceiling["stats"]["mean_candidates_per_customer"]
    assert release["diagnostics"]["union_candidate_rows"] == ceiling["stats"]["n_candidate_rows"]
    assert release["meta"]["cohort_customer_count"] == ceiling["stats"]["n_customers"]
    assert {item["source"]: item["candidate_rows"] for item in release["diagnostics"]["source_metrics"]} == {
        source: ceiling["stats"][f"rows_from_{source}"]
        for source in REQUIRED_SOURCES
    }
    serialized = release_path.read_text()
    assert "customer_id" not in serialized
    assert "raw_customer_id" not in serialized
    assert re.search(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", serialized) is None
