from __future__ import annotations

import copy
import dataclasses
import hashlib
import io
import json
from pathlib import Path

import pytest
import numpy as np
import torch

from marketrank.retrieval.inference_bundle import (
    REQUIRED_ARTIFACTS,
    InferenceBundleError,
    load_inference_bundle,
    read_inference_bundle_manifest,
    validate_inference_bundle_manifest,
)
from marketrank.retrieval_v2.bundle import assemble_inference_bundle
from marketrank.retrieval_v2.dataset import (
    RetrievalDatasetError,
    build_retrieval_dataset,
)
from marketrank.retrieval_v2.model import (
    RetrievalModelError,
    train_and_select_retriever,
    validate_model_inputs,
)

FIXTURE = Path("tests/fixtures/contracts_v2/inference-bundle.json")


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def _write_complete_bundle(root: Path) -> Path:
    root.mkdir()
    value = _fixture()
    artifacts = {}
    hashes = {}
    for name in REQUIRED_ARTIFACTS:
        if name == "checksums":
            continue
        filename = (
            f"{name}.json"
            if name in {"training_arguments", "metrics", "customer_vocabulary", "article_vocabulary", "schema"}
            else f"{name}.bin"
        )
        if name == "catalog_arrays":
            filename = "catalog_arrays.npz"
            buffer = io.BytesIO()
            np.savez(
                buffer,
                article_ids=np.asarray(["a1"], dtype="U"),
                article_vectors=np.asarray([[1, 0, 0, 0]], dtype=np.float32),
            )
            content = buffer.getvalue()
        elif name == "customer_vocabulary":
            content = b'{"synthetic_c1":1}\n'
        elif name == "article_vocabulary":
            content = b'{"a1":1}\n'
        else:
            content = b"{}\n" if filename.endswith(".json") else f"synthetic:{name}\n".encode()
        (root / filename).write_bytes(content)
        hashes[name] = hashlib.sha256(content).hexdigest()
        artifacts[name] = {"path": filename, "sha256": hashes[name]}
    checksum_content = "".join(f"{hashes[name]}  {name}\n" for name in sorted(hashes)).encode()
    (root / "SHA256SUMS").write_bytes(checksum_content)
    artifacts["checksums"] = {
        "path": "SHA256SUMS",
        "sha256": hashlib.sha256(checksum_content).hexdigest(),
    }
    value["artifacts"] = artifacts
    value["input_signature"] = {
        "customer_inputs": value["allowed_customer_inputs"],
        "tensor_inputs": {
            "customer_indices": {"dtype": "int64", "rank": 1},
            "recent_article_indices": {"dtype": "int64", "rank": 2, "width": 10},
            "numeric_features": {"dtype": "float32", "rank": 2, "width": 4},
        },
        "article_inputs": ["article_id_embedding"],
        "output_dtype": "float32",
    }
    (root / "manifest.json").write_text(json.dumps(value))
    return root


def test_frozen_manifest_is_valid_and_blocks_early_scoring():
    bundle = read_inference_bundle_manifest(FIXTURE)
    assert bundle.bundle_id == "v2_pit_safe_synthetic_fixture"
    assert bundle.dimension == 4
    bundle.assert_scoring_date("2020-07-15")
    with pytest.raises(InferenceBundleError, match="available only after"):
        bundle.assert_scoring_date("2020-07-14")


@pytest.mark.parametrize("field", ["age", "age_bucket", "club_member_status", "fn", "active"])
def test_manifest_rejects_mutable_customer_input(field):
    value = _fixture()
    value["allowed_customer_inputs"].append(field)
    with pytest.raises(InferenceBundleError, match="allowed_customer_inputs"):
        validate_inference_bundle_manifest(value)


def test_manifest_rejects_reordered_or_overlapping_nested_slices():
    value = _fixture()
    value["retrieval_select"] = ["2020-06-30", "2020-07-14"]
    with pytest.raises(InferenceBundleError, match="overlap|chronology"):
        validate_inference_bundle_manifest(value)


def test_complete_bundle_checks_every_artifact(tmp_path):
    bundle = load_inference_bundle(_write_complete_bundle(tmp_path / "bundle"))
    assert bundle.bundle_id == "v2_pit_safe_synthetic_fixture"


def test_bundle_rejects_missing_artifact(tmp_path):
    root = _write_complete_bundle(tmp_path / "bundle")
    (root / "metrics.json").unlink()
    with pytest.raises(InferenceBundleError, match="metrics.*missing"):
        load_inference_bundle(root)


def test_bundle_rejects_checksum_mismatch(tmp_path):
    root = _write_complete_bundle(tmp_path / "bundle")
    (root / "model_weights.bin").write_bytes(b"corrupt")
    with pytest.raises(InferenceBundleError, match="model_weights.*checksum"):
        load_inference_bundle(root)


def test_bundle_rejects_forbidden_field_inside_schema_artifact(tmp_path):
    root = _write_complete_bundle(tmp_path / "bundle")
    path = root / "schema.json"
    path.write_text(json.dumps({"features": ["customer_id_embedding", "age"]}))
    value = json.loads((root / "manifest.json").read_text())
    value["artifacts"]["schema"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "manifest.json").write_text(json.dumps(value))
    with pytest.raises(InferenceBundleError, match="mutable customer fields"):
        load_inference_bundle(root)


def test_bundle_rejects_raw_customer_id_inside_vocabulary_artifact(tmp_path):
    root = _write_complete_bundle(tmp_path / "bundle")
    path = root / "customer_vocabulary.json"
    path.write_text(json.dumps({"a" * 64: 1}))
    value = json.loads((root / "manifest.json").read_text())
    value["artifacts"]["customer_vocabulary"]["sha256"] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    (root / "manifest.json").write_text(json.dumps(value))
    with pytest.raises(InferenceBundleError, match="raw 64-hex"):
        load_inference_bundle(root)


def test_bundle_directory_requires_physical_artifact_map(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(_fixture()))
    with pytest.raises(InferenceBundleError, match="map every required artifact"):
        load_inference_bundle(root)


def test_complete_bundle_requires_executable_tensor_signature(tmp_path):
    root = _write_complete_bundle(tmp_path / "bundle")
    value = json.loads((root / "manifest.json").read_text())
    value["input_signature"]["tensor_inputs"].pop("numeric_features")
    (root / "manifest.json").write_text(json.dumps(value))
    with pytest.raises(InferenceBundleError, match="tensor input signature keys mismatch"):
        load_inference_bundle(root)


def test_manifest_rejects_unknown_top_level_fields():
    value = copy.deepcopy(_fixture())
    value["probability"] = 0.9
    with pytest.raises(InferenceBundleError, match="extra"):
        validate_inference_bundle_manifest(value)


def test_manifest_rejects_unlisted_customer_input_in_signature():
    value = _fixture()
    value["input_signature"] = {"customer_inputs": ["customer_id_embedding", "income"]}
    with pytest.raises(InferenceBundleError, match="outside the allowlist"):
        validate_inference_bundle_manifest(value)


def _training_inputs():
    customers = {"synthetic_c1": 1, "synthetic_c2": 2}
    articles = {"a1": 1, "a2": 2}

    def row(customer, day, positive, recent):
        return {
            "customer_id": customer,
            "scoring_date": day,
            "positive_article_id": positive,
            "recent_article_sequence": recent,
            "days_since_last_purchase": 1,
            "purchase_count_7d": 1,
            "purchase_count_30d": 2,
            "purchase_count_90d": 3,
        }

    fit = build_retrieval_dataset(
        [
            row("synthetic_c1", "2020-06-29", "a1", ["a1"]),
            row("synthetic_c2", "2020-06-30", "a2", ["a2"]),
        ],
        split="retrieval_fit",
        customer_vocabulary=customers,
        article_vocabulary=articles,
        recent_k=2,
    )
    select = build_retrieval_dataset(
        [
            row("synthetic_c1", "2020-07-01", "a1", ["a1"]),
            row("synthetic_c2", "2020-07-02", "a2", ["a2"]),
        ],
        split="retrieval_select",
        customer_vocabulary=customers,
        article_vocabulary=articles,
        recent_k=2,
    )
    return customers, articles, fit, select


def test_dataset_rejects_mutable_fields_and_wrong_nested_slice():
    customers, articles, _, _ = _training_inputs()
    row = {
        "customer_id": "synthetic_c1",
        "scoring_date": "2020-06-30",
        "positive_article_id": "a1",
        "recent_article_sequence": ["a1"],
        "days_since_last_purchase": 1,
        "purchase_count_7d": 1,
        "purchase_count_30d": 2,
        "purchase_count_90d": 3,
        "age": 30,
    }
    with pytest.raises(RetrievalDatasetError, match="mutable customer fields"):
        build_retrieval_dataset(
            [row], split="retrieval_fit", customer_vocabulary=customers,
            article_vocabulary=articles, recent_k=2,
        )
    row.pop("age")
    row["scoring_date"] = "2020-07-01"
    with pytest.raises(RetrievalDatasetError, match="outside the frozen retrieval_fit"):
        build_retrieval_dataset(
            [row], split="retrieval_fit", customer_vocabulary=customers,
            article_vocabulary=articles, recent_k=2,
        )


def test_synthetic_training_and_selection_are_deterministic():
    customers, articles, fit, select = _training_inputs()
    first = train_and_select_retriever(
        fit, select, n_customers=len(customers), n_articles=len(articles), seed=17
    )
    second = train_and_select_retriever(
        fit, select, n_customers=len(customers), n_articles=len(articles), seed=17
    )
    assert first.training_arguments == second.training_arguments
    assert first.metrics == second.metrics
    for name, tensor in first.model.state_dict().items():
        assert torch.equal(tensor, second.model.state_dict()[name])


def test_model_and_training_config_reject_extra_mutable_input():
    _, _, fit, select = _training_inputs()
    tensors = fit.tensors()
    tensors["age"] = torch.ones(len(fit), dtype=torch.float32)
    with pytest.raises(RetrievalModelError, match="extra=.*age"):
        validate_model_inputs(tensors)
    with pytest.raises(RetrievalModelError, match="configuration keys mismatch"):
        train_and_select_retriever(
            fit,
            select,
            n_customers=2,
            n_articles=2,
            configurations=[
                {
                    "configuration_id": "unsafe",
                    "dimension": 4,
                    "epochs": 1,
                    "lr": 0.1,
                    "age": True,
                }
            ],
        )


def test_complete_bundle_assembler_is_checksum_complete_and_deterministic(tmp_path):
    customers, articles, fit, select = _training_inputs()
    result = train_and_select_retriever(
        fit, select, n_customers=2, n_articles=2, seed=19
    )
    with torch.no_grad():
        vectors = result.model.article(torch.arange(1, 3, dtype=torch.int64)).numpy()
    roots = []
    for name in ("one", "two"):
        root = assemble_inference_bundle(
            tmp_path / name,
            bundle_id="v2_pit_safe_synthetic_trained",
            data_mode="synthetic_fixture",
            training_result=result,
            customer_vocabulary=customers,
            article_vocabulary=articles,
            article_ids=["a1", "a2"],
            article_vectors=vectors,
            recent_k=2,
            code_revision="synthetic-test",
            dependency_lock_sha256="a" * 64,
        )
        roots.append(root)
        loaded = load_inference_bundle(root)
        assert loaded.complete is True
        assert loaded.data_mode == "synthetic_fixture"
        assert loaded.artifact_path("catalog_arrays") == (root / "catalog_arrays.npz").resolve()
    for filename in sorted(path.name for path in roots[0].iterdir()):
        assert (roots[0] / filename).read_bytes() == (roots[1] / filename).read_bytes()


def test_bundle_assembler_rejects_forbidden_training_arguments_and_raw_customer_ids(tmp_path):
    customers, articles, fit, select = _training_inputs()
    result = train_and_select_retriever(
        fit, select, n_customers=2, n_articles=2, seed=23
    )
    with torch.no_grad():
        vectors = result.model.article(torch.arange(1, 3, dtype=torch.int64)).numpy()
    unsafe_result = dataclasses.replace(
        result,
        training_arguments={**result.training_arguments, "age": 30},
    )
    common = dict(
        bundle_id="v2_pit_safe_synthetic_trained",
        data_mode="synthetic_fixture",
        article_vocabulary=articles,
        article_ids=["a1", "a2"],
        article_vectors=vectors,
        recent_k=2,
        code_revision="synthetic-test",
        dependency_lock_sha256="a" * 64,
    )
    with pytest.raises(ValueError, match="training arguments.*forbidden mutable"):
        assemble_inference_bundle(
            tmp_path / "unsafe-args",
            training_result=unsafe_result,
            customer_vocabulary=customers,
            **common,
        )
    with pytest.raises(ValueError, match="raw 64-hex"):
        assemble_inference_bundle(
            tmp_path / "unsafe-id",
            training_result=result,
            customer_vocabulary={"a" * 64: 1, "synthetic_c2": 2},
            **common,
        )


def test_retriever_training_requires_fit_then_select():
    _, _, fit, select = _training_inputs()
    with pytest.raises(RetrievalModelError, match="requires retrieval_fit"):
        train_and_select_retriever(
            select, fit, n_customers=2, n_articles=2
        )
