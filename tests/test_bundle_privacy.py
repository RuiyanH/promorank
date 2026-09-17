import pytest

from marketrank.jobs.audit_workbench_bundle import audit


def test_browser_bundle_rejects_restricted_artifacts_and_secrets(tmp_path):
    (tmp_path/"dist/client").mkdir(parents=True)
    (tmp_path/"public").mkdir()
    (tmp_path/"dist/client/app.js").write_text("synthetic safe application")
    assert audit(tmp_path)["files_scanned"]==1
    forbidden=tmp_path/"public/customer.parquet"
    forbidden.write_bytes(b"synthetic artifact")
    with pytest.raises(ValueError,match="restricted artifact"):audit(tmp_path)
    forbidden.unlink()
    (tmp_path/"dist/client/app.js").write_text("-----BEGIN PRIVATE KEY-----")
    with pytest.raises(ValueError,match="secret material"):audit(tmp_path)
