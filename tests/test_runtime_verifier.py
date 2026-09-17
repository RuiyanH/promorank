import json
import socket
from pathlib import Path

import pytest

from marketrank.jobs.verify_replay_runtime import launch_service, run
from marketrank.replay.release import build_release


def test_verifier_owns_only_its_child_and_records_actual_http(tmp_path):
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1",8070))==0:
            pytest.skip("local API already occupies the explicit verification port")
    fixture=json.loads(Path("tests/fixtures/contracts_v2/api-recommendations.json").read_text())
    release=tmp_path/"release"
    build_release(release,release_id="SYNTHETIC_RUNTIME_QA",key=b"s"*32,
        responses=[{**fixture,"customer_ref":f"v2c_{customer:024x}","as_of":day}
            for customer in range(2) for day in ("2020-09-09","2020-09-16")],
        quality={},provenance={"data_mode":"synthetic_fixture"})
    with launch_service(release) as context:
        with pytest.raises(ValueError,match="occupied"):
            with launch_service(release):pass
        report=run(release,tmp_path/"runtime.json",runtime_context=context)
        assert report["requests"]==34
        assert report["cold_process_startup_seconds"]>0
        assert report["api_rss_after_startup_bytes"]>0
        assert report["api_rss_after_workload_bytes"]>0
        assert "pid" not in report
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1",8070))!=0
