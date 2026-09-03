import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from marketrank.jobs import build_candidates, build_daily_ann
from marketrank import partitions as partition_state
from marketrank.retrieval.daily_ann import (
    partition_path,
    validate_daily_ann_range,
    write_daily_ann_partition,
)

INPUT_HASHES = {"catalog": "1" * 64, "queries": "2" * 64, "article_first_seen": "3" * 64}


def test_build_candidates_exposes_ann_root_contract_seam():
    args = build_candidates.parse_args(
        [
            "--ann-root", "/tmp/scratch/ann",
            "--candidate-config", "tests/fixtures/contracts_v2/candidate-config.json",
            "--scratch-root", "/tmp/scratch",
            "--ann-bundle-id", "v2_pit_safe_synthetic_fixture",
            "--ann-cohort-id", "synthetic-cohort",
            "--spine-type", "active_day",
        ]
    )
    assert args.ann_root == Path("/tmp/scratch/ann")
    assert args.candidate_config == Path("tests/fixtures/contracts_v2/candidate-config.json")
    assert args.spine_type == "active_day"


def test_ann_root_preflight_binds_frozen_config_and_scratch(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    args = build_candidates.parse_args(
        [
            "--ann-root", str(scratch / "ann"),
            "--candidate-config", "tests/fixtures/contracts_v2/candidate-config.json",
            "--scratch-root", str(scratch),
            "--out", str(scratch / "candidates"),
            "--ann-bundle-id", "v2_pit_safe_synthetic_fixture",
            "--ann-cohort-id", "synthetic-cohort",
        ]
    )
    prepared = build_candidates.prepare_args(args)
    assert prepared.n_covisit == 40
    assert prepared.covisit_lookback == 30
    assert prepared.covisit_max_basket == 20
    assert prepared.recent_k == 10
    assert prepared.ann_candidate_config_id == "v2-five-source-30-40-40-40-50"


@pytest.mark.parametrize("omitted", ["--ann-bundle-id", "--ann-cohort-id"])
def test_ann_root_preflight_requires_bound_identity(tmp_path, omitted):
    values = {
        "--ann-bundle-id": "v2_pit_safe_synthetic_fixture",
        "--ann-cohort-id": "synthetic-cohort",
    }
    argv = [
        "--ann-root", str(tmp_path / "scratch" / "ann"),
        "--candidate-config", "tests/fixtures/contracts_v2/candidate-config.json",
        "--scratch-root", str(tmp_path / "scratch"),
        "--out", str(tmp_path / "scratch" / "candidates"),
    ]
    for flag, value in values.items():
        if flag != omitted:
            argv.extend([flag, value])
    with pytest.raises(SystemExit, match="requires --ann-bundle-id and --ann-cohort-id"):
        build_candidates.prepare_args(build_candidates.parse_args(argv))


def test_snapshot_single_day_guard_remains_unchanged():
    build_candidates.assert_snapshot_single_day(664, 664, Path("snapshot"), 664)
    with pytest.raises(SystemExit, match="single-day fixture"):
        build_candidates.assert_snapshot_single_day(664, 665, Path("snapshot"), 664)


def test_legacy_snapshot_defaults_remain_compatible():
    prepared = build_candidates.prepare_args(
        build_candidates.parse_args(["--ann-snapshot", "snapshot.parquet"])
    )
    assert prepared.n_covisit == 60
    assert prepared.covisit_lookback == 90
    assert prepared.covisit_max_basket == 50


def test_daily_job_rejects_numeric_identifier_arrays():
    with pytest.raises(ValueError, match="numeric IDs are forbidden"):
        build_daily_ann._string_ids(np.asarray([1, 2], dtype=np.int64), "customer_ids")


def test_partition_mutation_invalidates_completed_chunk_resume(tmp_path):
    scratch = tmp_path / "scratch"
    ann_root = scratch / "ann"
    output = scratch / "candidates"
    rows = [
        {
            "customer_id": "synthetic_c1",
            "day_index": 664,
            "article_id": "a1",
            "source": "ann",
            "source_rank": 1,
        }
    ]
    write_daily_ann_partition(
        ann_root,
        scoring_date="2020-07-15",
        day_index=664,
        bundle_id="v2_pit_safe_synthetic_fixture",
        candidate_config_id="v2-five-source-30-40-40-40-50",
        cohort_id="synthetic-cohort",
        spine_type="active_day",
        depth=50,
        eligible_article_count=2,
        rows=rows,
        input_hashes=INPUT_HASHES,
    )
    args = build_candidates.prepare_args(
        build_candidates.parse_args(
            [
                "--ann-root", str(ann_root),
                "--candidate-config", "tests/fixtures/contracts_v2/candidate-config.json",
                "--scratch-root", str(scratch),
                "--out", str(output),
                "--ann-bundle-id", "v2_pit_safe_synthetic_fixture",
                "--ann-cohort-id", "synthetic-cohort",
            ]
        )
    )
    manifests = validate_daily_ann_range(ann_root, ["2020-07-15"])
    original_content = build_candidates.content_of(args, manifests)
    chunk_path = partition_state.part_path(output, build_candidates.CHUNK_KEY, 664)
    chunk_path.mkdir(parents=True)
    (chunk_path / "_SUCCESS").write_bytes(b"")
    partition_state.write_part_meta(
        output,
        build_candidates.CHUNK_KEY,
        664,
        {"rows": 1, "args": original_content},
    )
    assert partition_state.part_state(
        output,
        build_candidates.CHUNK_KEY,
        664,
        original_content,
        build_candidates.CHUNK_CONTENT_ARGS,
    ) == partition_state.OK

    ann_part = partition_path(ann_root, "2020-07-15")
    changed = {**rows[0], "article_id": "a2"}
    payload = (json.dumps(changed, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (ann_part / "records.jsonl").write_bytes(payload)
    manifest_path = ann_part / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    digest = hashlib.sha256(payload).hexdigest()
    manifest["partition_checksum"] = digest
    manifest["files"]["records.jsonl"] = digest
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")

    changed_manifests = validate_daily_ann_range(ann_root, ["2020-07-15"])
    changed_content = build_candidates.content_of(args, changed_manifests)
    assert partition_state.part_state(
        output,
        build_candidates.CHUNK_KEY,
        664,
        changed_content,
        build_candidates.CHUNK_CONTENT_ARGS,
    ) == partition_state.MISMATCH
