import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from marketrank.replay.release import build_release, customer_ref, validate_public_metadata, validate_release_status
from marketrank.service.app import create_app


def test_release_refs_are_key_and_release_scoped():
    assert customer_ref(b"a"*32,"one","internal")!=customer_ref(b"a"*32,"two","internal")
    assert customer_ref(b"a"*32,"one","internal")!=customer_ref(b"b"*32,"one","internal")


def test_verified_status_requires_external_acceptance():
    with pytest.raises(ValueError):validate_release_status("verified",{"quality_gate_passed":True})
    validate_release_status("candidate",{"quality_gate_passed":False})


@pytest.mark.parametrize("value",[{"customer_id":"x"},{"nested":{"path":"/private"}},{"id":"a"*64},{"confidence":.8},
    {"note":"customer "+"a"*64},{"note":"v2c_"+"a"*24}])
def test_public_quality_rejects_restricted_metadata(value):
    with pytest.raises(ValueError):validate_public_metadata(value)


def test_post_start_mutation_fails_closed_and_errors_redact_inputs(tmp_path):
    fixture=json.loads(Path("tests/fixtures/contracts_v2/api-recommendations.json").read_text())
    root=tmp_path/"release"
    build_release(root,release_id="test",key=b"a"*32,
        responses=[{**fixture,"as_of":day} for day in ("2020-09-09","2020-09-16")],quality={},provenance={})
    client=TestClient(create_app(root),base_url="http://localhost")
    response=client.get("/api/v2/releases/test/customers",params={"limit":"sensitive_input"})
    assert response.status_code==422 and "sensitive_input" not in response.text
    assert client.get("/health/ready").status_code==200
    with (root/"replay.duckdb").open("ab") as stream:stream.write(b"mutation")
    assert client.get("/health/live").status_code==200
    assert client.get("/health/ready").status_code==503
