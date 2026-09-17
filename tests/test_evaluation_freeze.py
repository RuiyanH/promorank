import json
from pathlib import Path

import pytest

from marketrank.evidence import write_json,sha256
from marketrank.ranking.freeze import create_freeze,validate_freeze
from marketrank.jobs.train_ranker import load_frames


def test_freeze_binds_artifacts_and_refuses_second_open(tmp_path):
    model=tmp_path/"ranker";calibration=tmp_path/"calibration";source=tmp_path/"source"
    model.mkdir();calibration.mkdir();source.mkdir()
    (model/"selected.txt").write_text("synthetic model")
    (calibration/"calibrator.joblib").write_bytes(b"synthetic artifact")
    write_json(model/"manifest.json",{"frozen":True,"selected":{"model_file":"selected.txt"}})
    write_json(calibration/"manifest.json",{"model_manifest_sha256":sha256(model/"manifest.json")})
    write_json(source/"manifest.json",{"transaction_snapshot":"synthetic"})
    path=create_freeze(tmp_path,model=model,calibrator=calibration,source=source)
    assert validate_freeze(path)["bootstrap_replicates"]==2000
    with pytest.raises(ValueError):create_freeze(tmp_path,model=model,calibrator=calibration,source=source)
    (model/"selected.txt").write_text("changed")
    with pytest.raises(ValueError):validate_freeze(path)


def test_loader_rejects_incomplete_split_before_training(tmp_path):
    write_json(tmp_path/"2020-07-15/manifest.json",{})
    with pytest.raises(ValueError,match="complete frozen split"):
        load_frames(tmp_path,"ranker_fit")
