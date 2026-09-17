"""Explicitly synthetic local UI QA server; never used as release evidence."""
import json
import tempfile
from pathlib import Path

import uvicorn

from marketrank.replay.release import build_release
from marketrank.service.app import create_app


if __name__=="__main__":
    fixture=json.loads(Path("tests/fixtures/contracts_v2/api-recommendations.json").read_text())
    responses=[{**fixture,"customer_ref":f"v2c_{c:024x}","as_of":day}
               for c in range(50) for day in ("2020-09-09","2020-09-16")]
    with tempfile.TemporaryDirectory(prefix="marketrank-synthetic-ui-") as directory:
        root=Path(directory)/"release"
        build_release(root,release_id="SYNTHETIC_UI_QA_ONLY",key=b"synthetic-test-key-not-a-secret!!",responses=responses,
            quality={"evaluation":"synthetic_fixture"},provenance={"data_mode":"synthetic_fixture"})
        uvicorn.run(create_app(root),host="127.0.0.1",port=8070,access_log=False)
