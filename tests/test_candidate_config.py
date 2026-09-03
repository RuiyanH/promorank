from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from marketrank.candidate_pipeline.config import (
    CandidateConfigError,
    EXPECTED_CONFIG_ID,
    load_candidate_config,
    validate_candidate_config,
)

FIXTURE = Path("tests/fixtures/contracts_v2/candidate-config.json")


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_frozen_candidate_config_has_stable_id_and_depths():
    config = load_candidate_config(FIXTURE)
    assert config.candidate_config_id == EXPECTED_CONFIG_ID
    assert [config.depth(name) for name in config.source_names] == [30, 40, 40, 40, 50]
    assert config.recent_k == 10
    assert config.warm_up_days == 90


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["sources"].pop("ann"), "sources keys mismatch"),
        (lambda value: value["sources"].update({"mystery": {"depth": 1}}), "sources keys mismatch"),
        (lambda value: value["sources"]["ann"].update({"depth": 49}), "depth must be 50"),
        (lambda value: value["sources"]["covisit"].update({"recent_k": 9}), "recent_k=10"),
        (lambda value: value.update({"schema_version": "candidate-config.v1"}), "schema_version"),
        (lambda value: value.update({"candidate_config_id": "same-name-wrong-content"}), "candidate_config_id"),
    ],
)
def test_candidate_config_rejects_contract_drift(mutation, message):
    value = copy.deepcopy(_fixture())
    mutation(value)
    with pytest.raises(CandidateConfigError, match=message):
        validate_candidate_config(value)


def test_candidate_config_copy_does_not_mutate_frozen_value():
    config = load_candidate_config(FIXTURE)
    copy_value = config.as_dict()
    copy_value["sources"]["ann"]["depth"] = 1
    assert config.depth("ann") == 50
