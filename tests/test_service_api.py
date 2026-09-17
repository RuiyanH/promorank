import copy
import json
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from marketrank.replay.release import build_release, validate_recommendations, verify_release, open_readonly_release
from marketrank.service.app import create_app


@pytest.fixture
def release(tmp_path):
    fixture = json.loads(Path("tests/fixtures/contracts_v2/api-recommendations.json").read_text())
    responses = []
    for customer in range(20):
        for day in ("2020-09-09", "2020-09-16"):
            responses.append({**fixture, "customer_ref": f"v2c_{customer:024x}", "as_of": day})
    root = tmp_path / "release"
    build_release(root, release_id="test_release", key=b"s"*32, responses=responses,
                  quality={"evaluation": "synthetic_fixture"}, provenance={"data_mode": "synthetic_fixture"})
    return root


def test_golden_contract_rejects_hybrids_and_unavailable_dates():
    value = json.loads(Path("tests/fixtures/contracts_v2/api-recommendations.json").read_text())
    validate_recommendations(value)
    hybrid = copy.deepcopy(value)
    hybrid["recommendations"][0]["probability"] = .6
    with pytest.raises(ValueError):
        validate_recommendations(hybrid)
    value["as_of"] = "2020-08-12"
    with pytest.raises(ValueError):
        validate_recommendations(value)


def test_json_schema_and_openapi_reconcile_with_frozen_fixture(release):
    import jsonschema
    from marketrank.service.contracts import RecommendationsResponse
    value=json.loads(Path("tests/fixtures/contracts_v2/api-recommendations.json").read_text())
    jsonschema.validate(value,json.loads(Path("contracts/workbench-api-v2.schema.json").read_text()))
    jsonschema.validate(value,RecommendationsResponse.model_json_schema())
    manifest=json.loads((release/"manifest.json").read_text())
    jsonschema.validate(manifest,json.loads(Path("contracts/replay-release-v2.schema.json").read_text()))
    api=TestClient(create_app(release),base_url="http://localhost").get("/openapi.json").json()
    response=api["paths"]["/api/v2/releases/{release_id}/customers/{customer_ref}/recommendations"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"]["$ref"].endswith("/RecommendationsResponse")


def test_readonly_api_pagination_queries_and_privacy(release):
    client = TestClient(create_app(release, cursor_key=b"c"*32),base_url="http://localhost")
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    prefix = "/api/v2/releases/test_release"
    page = client.get(prefix + "/customers", params={"limit": 3}).json()
    assert len(page["customers"]) == 3 and page["next_cursor"]
    second = client.get(prefix + "/customers", params={"limit": 3, "cursor": page["next_cursor"]}).json()
    assert set(x["customer_ref"] for x in page["customers"]).isdisjoint(x["customer_ref"] for x in second["customers"])
    assert client.get(prefix + "/customers", params={"cursor": page["next_cursor"], "q": "changed"}).status_code == 400
    assert client.get(prefix + "/customers", params={"cursor": page["next_cursor"][:-5]+"abcde"}).status_code == 400
    assert client.get(prefix + "/customers", params={"sort": "DROP TABLE customers"}).status_code == 400
    assert client.get(prefix + "/customers", params={"q": "' OR 1=1 --"}).json()["customers"] == []
    assert client.get(prefix + "/customers", params={"limit": 101}).status_code == 422
    ref = page["customers"][0]["customer_ref"]
    response = client.get(prefix + f"/customers/{ref}/recommendations", params={"as_of": "2020-09-09"})
    assert response.status_code == 200
    validate_recommendations(response.json())
    assert client.get(prefix + f"/customers/{ref}/recommendations", params={"as_of": "2020-07-15"}).status_code == 400
    assert client.get(prefix + "/customers/" + "a"*64 + "/recommendations", params={"as_of": "2020-09-09"}).status_code == 404
    assert str(release) not in response.text
    assert client.post(prefix + "/customers").status_code == 405
    with duckdb.connect(str(release / "replay.duckdb"), read_only=True) as db:
        with pytest.raises(duckdb.Error):
            db.execute("DELETE FROM customers")
    assert client.get("/health/live", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/health/live", headers={"host": "testserver"}).status_code == 400
    assert client.get("/docs").status_code==404
    with open_readonly_release(release) as db:
        assert db.execute("SELECT current_setting('enable_external_access')").fetchone()[0] is False
        with pytest.raises(duckdb.Error):db.execute("SELECT * FROM read_text(?)",[str(release/"manifest.json")])


def test_corrupt_release_stays_live_but_not_ready(release):
    with (release / "replay.duckdb").open("ab") as stream:
        stream.write(b"corrupt")
    with pytest.raises(ValueError):
        verify_release(release)
    client = TestClient(create_app(release),base_url="http://localhost")
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503
    assert client.get("/api/v2/releases").status_code == 503
    with pytest.raises(ValueError):
        create_app(release, host="0.0.0.0")


def test_release_rejects_extra_tables_even_with_an_updated_file_checksum(release):
    from marketrank.evidence import sha256,write_json
    with duckdb.connect(str(release/"replay.duckdb")) as db:
        db.execute("CREATE TABLE restricted_extra(customer_id VARCHAR)")
    manifest=json.loads((release/"manifest.json").read_text())
    manifest["database_sha256"]=sha256(release/"replay.duckdb")
    write_json(release/"manifest.json",manifest)
    with pytest.raises(ValueError,match="unexpected tables"):verify_release(release)


@pytest.mark.parametrize("bad",[None,[],{"release_id":None}])
def test_malformed_manifest_stays_live_but_not_ready(release,bad):
    (release/"manifest.json").write_text(json.dumps(bad))
    client=TestClient(create_app(release),base_url="http://localhost")
    assert client.get("/health/live").status_code==200
    assert client.get("/health/ready").status_code==503


def test_recommendations_reject_coercion_and_wrong_artifact_dates():
    fixture=json.loads(Path("tests/fixtures/contracts_v2/api-recommendations.json").read_text())
    for field,value in (("position",True),("ordering_score",True),("ordering_score","0.5")):
        changed=copy.deepcopy(fixture);changed["recommendations"][0][field]=value
        with pytest.raises(ValueError):validate_recommendations(changed)
    changed=copy.deepcopy(fixture);changed["model_available_after"]="2020-07-01"
    with pytest.raises(ValueError):validate_recommendations(changed)
