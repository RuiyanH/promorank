from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from marketrank.candidate_pipeline.config import load_candidate_config
from marketrank.candidate_pipeline.guards import UnsafeOutputPath, assert_large_output_path
from marketrank.jobs.build_daily_ann import build_daily_partition
from marketrank.retrieval.daily_ann import (
    DailyAnnError,
    partition_path,
    read_daily_ann_partition,
    read_daily_ann_range,
    write_daily_ann_partition,
)
from marketrank.retrieval.inference_bundle import read_inference_bundle_manifest
from marketrank.retrieval_v2.exact import exact_daily_retrieval
from marketrank.retrieval_v2.exact import RetrievalError

BUNDLE_FIXTURE = Path("tests/fixtures/contracts_v2/inference-bundle.json")
CONFIG_FIXTURE = Path("tests/fixtures/contracts_v2/candidate-config.json")
INPUT_HASHES = {"catalog": "1" * 64, "queries": "2" * 64, "article_first_seen": "3" * 64}


def _catalog():
    return {
        "article_ids": ["0000000004", "0000000003", "0000000002", "0000000001"],
        "article_vectors": np.asarray(
            [[9.0, 0.0], [1.0, 0.0], [1.0, 0.0], [0.5, 0.0]], dtype=np.float32
        ),
        "first_seen": {
            "0000000001": "2019-01-01",
            "0000000002": "2020-07-01",
            "0000000003": "2020-07-14",
            "0000000004": "2020-07-15",
        },
    }


def _rows(day_index=664):
    return [
        {"customer_id": "synthetic_customer_001", "day_index": day_index,
         "article_id": "0000000002", "source": "ann", "source_rank": 1},
        {"customer_id": "synthetic_customer_001", "day_index": day_index,
         "article_id": "0000000001", "source": "ann", "source_rank": 2},
    ]


def _write(root: Path, date="2020-07-15", day_index=664, bundle="v2_pit_safe_synthetic_fixture"):
    return write_daily_ann_partition(
        root,
        scoring_date=date,
        day_index=day_index,
        bundle_id=bundle,
        candidate_config_id="v2-five-source-30-40-40-40-50",
        cohort_id="synthetic-cohort",
        spine_type="active_day",
        depth=50,
        eligible_article_count=3,
        rows=_rows(day_index),
        input_hashes=INPUT_HASHES,
    )


def test_exact_search_tie_break_filter_and_refill_are_batch_stable():
    catalog = _catalog()
    kwargs = dict(
        article_ids=catalog["article_ids"],
        article_vectors=catalog["article_vectors"],
        customer_ids=["synthetic_c2", "synthetic_c1"],
        customer_vectors=np.asarray([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32),
        article_first_seen=catalog["first_seen"],
        scoring_date="2020-07-15",
        day_index=664,
        depth=3,
    )
    one = exact_daily_retrieval(**kwargs, batch_size=1)
    many = exact_daily_retrieval(**kwargs, batch_size=99)
    assert one == many
    assert [row["article_id"] for row in one if row["customer_id"] == "synthetic_c1"] == [
        "0000000002", "0000000003", "0000000001"
    ]
    assert all(row["article_id"] != "0000000004" for row in one)


def test_later_eligibility_does_not_mutate_earlier_candidates():
    catalog = _catalog()
    common = dict(
        article_ids=catalog["article_ids"], article_vectors=catalog["article_vectors"],
        customer_ids=["synthetic_c1"], customer_vectors=np.asarray([[1.0, 0.0]], dtype=np.float32),
        article_first_seen=catalog["first_seen"], day_index=664, depth=2,
    )
    earlier = exact_daily_retrieval(**common, scoring_date="2020-07-15")
    exact_daily_retrieval(**{**common, "day_index": 665}, scoring_date="2020-07-16")
    repeated = exact_daily_retrieval(**common, scoring_date="2020-07-15")
    assert earlier == repeated


def test_exact_search_rejects_dtype_drift_date_mismatch_and_raw_customer_id():
    catalog = _catalog()
    base = dict(
        article_ids=catalog["article_ids"],
        article_vectors=catalog["article_vectors"],
        customer_ids=["synthetic_c1"],
        customer_vectors=np.asarray([[1.0, 0.0]], dtype=np.float32),
        article_first_seen=catalog["first_seen"],
        scoring_date="2020-07-15",
        day_index=664,
        depth=2,
    )
    with pytest.raises(RetrievalError, match="dtype float32"):
        exact_daily_retrieval(**{**base, "customer_vectors": np.asarray([[1.0, 0.0]], dtype=np.float64)})
    with pytest.raises(RetrievalError, match="day_index does not match"):
        exact_daily_retrieval(**{**base, "day_index": 665})
    with pytest.raises(RetrievalError, match="raw 64-hex"):
        exact_daily_retrieval(**{**base, "customer_ids": ["a" * 64]})


def test_partition_repeat_is_byte_identical_and_reused(tmp_path):
    first = _write(tmp_path)
    part = Path(first["path"])
    bytes_before = {path.name: path.read_bytes() for path in part.iterdir()}
    second = _write(tmp_path)
    bytes_after = {path.name: path.read_bytes() for path in part.iterdir()}
    assert first["state"] == "written"
    assert second["state"] == "reused"
    assert bytes_before == bytes_after


def test_partition_repairs_uncommitted_partial_write(tmp_path):
    part = partition_path(tmp_path, "2020-07-15")
    part.mkdir(parents=True)
    (part / "records.jsonl").write_text("partial")
    result = _write(tmp_path)
    assert result["state"] == "written"
    assert read_daily_ann_partition(tmp_path, "2020-07-15")["manifest"]["row_count"] == 2


@pytest.mark.parametrize("missing", ["_SUCCESS", "manifest.json", "records.jsonl"])
def test_partition_rejects_missing_component(tmp_path, missing):
    result = _write(tmp_path)
    (Path(result["path"]) / missing).unlink()
    with pytest.raises(DailyAnnError, match="incomplete"):
        read_daily_ann_partition(tmp_path, "2020-07-15")


def test_partition_rejects_corrupted_payload(tmp_path):
    result = _write(tmp_path)
    with (Path(result["path"]) / "records.jsonl").open("ab") as stream:
        stream.write(b"corrupt")
    with pytest.raises(DailyAnnError, match="checksum"):
        read_daily_ann_partition(tmp_path, "2020-07-15")


def test_partition_rejects_unmanifested_file_and_wrong_source(tmp_path):
    result = _write(tmp_path)
    part = Path(result["path"])
    (part / "unexpected.bin").write_bytes(b"unexpected")
    with pytest.raises(DailyAnnError, match="unmanifested"):
        read_daily_ann_partition(tmp_path, "2020-07-15")
    (part / "unexpected.bin").unlink()
    rows = _rows()
    rows[0]["source"] = "global_pop"
    other = tmp_path / "other"
    with pytest.raises(DailyAnnError, match="must be ann"):
        write_daily_ann_partition(
            other, scoring_date="2020-07-15", day_index=664,
            bundle_id="v2_pit_safe_synthetic_fixture",
            candidate_config_id="v2-five-source-30-40-40-40-50",
            cohort_id="synthetic-cohort", spine_type="active_day", depth=50,
            eligible_article_count=3, rows=rows,
            input_hashes=INPUT_HASHES,
        )


def test_partition_rejects_forbidden_or_private_fields(tmp_path):
    row = _rows()[0]
    row["age"] = 42
    with pytest.raises(DailyAnnError, match="keys mismatch|forbidden"):
        write_daily_ann_partition(
            tmp_path, scoring_date="2020-07-15", day_index=664,
            bundle_id="v2_pit_safe_synthetic_fixture",
            candidate_config_id="v2-five-source-30-40-40-40-50",
            cohort_id="synthetic-cohort", spine_type="active_day", depth=50,
            eligible_article_count=3, rows=[row],
            input_hashes=INPUT_HASHES,
        )


def test_missing_requested_date_partition_fails(tmp_path):
    with pytest.raises(DailyAnnError, match="incomplete"):
        read_daily_ann_range(tmp_path, ["2020-07-15"])


def test_partition_rejects_date_and_bundle_mismatch(tmp_path):
    _write(tmp_path)
    with pytest.raises(DailyAnnError, match="bundle_id mismatch"):
        read_daily_ann_partition(tmp_path, "2020-07-15", expected={"bundle_id": "wrong"})
    manifest_path = partition_path(tmp_path, "2020-07-15") / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["scoring_date"] = "2020-07-16"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(DailyAnnError, match="directory date"):
        read_daily_ann_partition(tmp_path, "2020-07-15")


def test_partition_rejects_day_index_date_mismatch(tmp_path):
    with pytest.raises(DailyAnnError, match="day_index does not match scoring_date"):
        _write(tmp_path, day_index=665)


def test_range_rejects_cross_bundle_partitions(tmp_path):
    _write(tmp_path)
    _write(tmp_path, date="2020-07-16", day_index=665, bundle="v2_pit_safe_other")
    with pytest.raises(DailyAnnError, match="mixes partition metadata"):
        read_daily_ann_range(tmp_path, ["2020-07-15", "2020-07-16"])


def test_range_rejects_mixed_data_modes(tmp_path):
    _write(tmp_path)
    _write(tmp_path, date="2020-07-16", day_index=665)
    manifest_path = partition_path(tmp_path, "2020-07-16") / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["data_mode"] = "non_release_pilot"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(DailyAnnError, match="data_mode"):
        read_daily_ann_range(tmp_path, ["2020-07-15", "2020-07-16"])


def test_non_synthetic_partition_requires_complete_bundle(tmp_path):
    with pytest.raises(DailyAnnError, match="complete verified bundle"):
        write_daily_ann_partition(
            tmp_path, scoring_date="2020-07-15", day_index=664,
            bundle_id="v2_pit_safe_pilot",
            candidate_config_id="v2-five-source-30-40-40-40-50",
            cohort_id="synthetic-cohort", spine_type="active_day", depth=50,
            eligible_article_count=3, rows=_rows(), input_hashes=INPUT_HASHES,
            data_mode="non_release_pilot",
        )


def test_complete_partition_rejects_changed_resume_content(tmp_path):
    _write(tmp_path)
    rows = _rows()
    rows[0]["article_id"] = "changed"
    with pytest.raises(DailyAnnError, match="different content"):
        write_daily_ann_partition(
            tmp_path, scoring_date="2020-07-15", day_index=664,
            bundle_id="v2_pit_safe_synthetic_fixture",
            candidate_config_id="v2-five-source-30-40-40-40-50",
            cohort_id="synthetic-cohort", spine_type="active_day", depth=50,
            eligible_article_count=3, rows=rows,
            input_hashes=INPUT_HASHES,
        )


def test_daily_build_supports_both_spines_without_mixing(tmp_path):
    bundle = read_inference_bundle_manifest(BUNDLE_FIXTURE)
    config = load_candidate_config(CONFIG_FIXTURE)
    result = build_daily_partition(
        bundle=bundle, config=config,
        article_ids=["a1", "a2"],
        article_vectors=np.asarray([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32),
        article_first_seen={"a1": "2020-01-01", "a2": "2020-01-02"},
        customer_ids=["synthetic-c1"],
        customer_vectors=np.asarray([[1, 0, 0, 0]], dtype=np.float32),
        scoring_date="2020-07-15", day_index=664, cohort_id="synthetic-replay",
        spine_type="replay_day", out_root=tmp_path,
    )
    assert result["manifest"]["spine_type"] == "replay_day"


def test_large_output_guard_rejects_repo_and_home(tmp_path):
    repo = Path.cwd().resolve()
    home = tmp_path / "home"
    home.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    assert assert_large_output_path(scratch / "ann", scratch, repository_root=repo, home_root=home) == (scratch / "ann").resolve()
    with pytest.raises(UnsafeOutputPath, match="repository"):
        assert_large_output_path(repo / "artifacts" / "v2", repo, repository_root=repo, home_root=home)
    with pytest.raises(UnsafeOutputPath, match="home"):
        assert_large_output_path(home / "scratch" / "ann", home / "scratch", repository_root=repo, home_root=home)
