"""Deterministic complete inference-bundle assembly for V2 retrieval."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from marketrank.retrieval.inference_bundle import (
    ALLOWED_CUSTOMER_INPUTS,
    ALLOWED_DATA_MODES,
    FORBIDDEN_CUSTOMER_INPUTS,
    REQUIRED_ARTIFACTS,
    load_inference_bundle,
)
from marketrank.candidate_pipeline.privacy import (
    CustomerIdentifierError,
    validate_customer_identifier,
)

from .dataset import executable_input_signature
from .model import RetrievalTrainingResult


class BundleAssemblyError(ValueError):
    """Inputs cannot form an immutable, complete V2 inference bundle."""


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _contains_forbidden_customer_field(value: Any) -> bool:
    forbidden = set(FORBIDDEN_CUSTOMER_INPUTS)
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in forbidden or _contains_forbidden_customer_field(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_customer_field(child) for child in value)
    return isinstance(value, str) and value.lower() in forbidden


def _validate_vocabulary(vocabulary: Mapping[str, int], name: str) -> None:
    if not isinstance(vocabulary, Mapping) or not vocabulary:
        raise BundleAssemblyError(f"{name} must be a non-empty mapping")
    values = list(vocabulary.values())
    if (
        any(not isinstance(key, str) or not key for key in vocabulary)
        or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values)
        or len(set(values)) != len(values)
    ):
        raise BundleAssemblyError(f"{name} must map unique non-empty string IDs to positive integers")


def _deterministic_array_archive(arrays: Mapping[str, np.ndarray]) -> bytes:
    """Write a stable ZIP of NPY members using a fixed timestamp and order."""

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(arrays):
            member = io.BytesIO()
            np.lib.format.write_array(member, np.asarray(arrays[name]), allow_pickle=False)
            info = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, member.getvalue())
    return output.getvalue()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def assemble_inference_bundle(
    output_dir: str | Path,
    *,
    bundle_id: str,
    data_mode: str,
    training_result: RetrievalTrainingResult,
    customer_vocabulary: Mapping[str, int],
    article_vocabulary: Mapping[str, int],
    article_ids: Sequence[str],
    article_vectors: np.ndarray,
    recent_k: int,
    code_revision: str,
    dependency_lock_sha256: str,
) -> Path:
    """Assemble and immediately re-read a checksum-complete bundle directory."""

    if data_mode not in ALLOWED_DATA_MODES:
        raise BundleAssemblyError(f"unsupported data_mode: {data_mode}")
    if not isinstance(bundle_id, str) or not bundle_id.startswith("v2_pit_safe"):
        raise BundleAssemblyError("bundle_id must identify the v2_pit_safe family")
    if not isinstance(code_revision, str) or not code_revision:
        raise BundleAssemblyError("code revision is required")
    if (
        not isinstance(dependency_lock_sha256, str)
        or len(dependency_lock_sha256) != 64
        or any(character not in "0123456789abcdef" for character in dependency_lock_sha256)
    ):
        raise BundleAssemblyError("dependency lock hash must be a lowercase SHA-256 digest")
    _validate_vocabulary(customer_vocabulary, "customer_vocabulary")
    _validate_vocabulary(article_vocabulary, "article_vocabulary")
    try:
        for customer_id in customer_vocabulary:
            validate_customer_identifier(customer_id)
    except CustomerIdentifierError as exc:
        raise BundleAssemblyError(str(exc)) from exc
    if _contains_forbidden_customer_field(training_result.training_arguments):
        raise BundleAssemblyError("training arguments contain a forbidden mutable customer field")
    if _contains_forbidden_customer_field(training_result.metrics):
        raise BundleAssemblyError("metrics contain a forbidden mutable customer field")
    vectors = np.asarray(article_vectors)
    if vectors.dtype != np.dtype(np.float32) or vectors.ndim != 2:
        raise BundleAssemblyError("article_vectors must be a rank-2 float32 matrix")
    if vectors.shape != (len(article_ids), training_result.model.dimension):
        raise BundleAssemblyError("article vectors do not match IDs or selected model dimension")
    if len(set(article_ids)) != len(article_ids) or any(not isinstance(item, str) for item in article_ids):
        raise BundleAssemblyError("article_ids must be unique strings")
    if set(article_vocabulary) != set(article_ids):
        raise BundleAssemblyError("article vocabulary and catalog IDs differ")

    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise BundleAssemblyError("bundle output directory must be absent or empty")
    output.mkdir(parents=True, exist_ok=True)
    state_arrays = {
        name: tensor.detach().cpu().numpy()
        for name, tensor in training_result.model.state_dict().items()
    }
    artifacts: dict[str, tuple[str, bytes]] = {
        "model_weights": ("model_weights.npz", _deterministic_array_archive(state_arrays)),
        "training_arguments": (
            "training_arguments.json",
            _canonical_json({**training_result.training_arguments, "data_mode": data_mode}),
        ),
        "metrics": ("metrics.json", _canonical_json(training_result.metrics)),
        "customer_vocabulary": (
            "customer_vocabulary.json",
            _canonical_json(dict(sorted(customer_vocabulary.items()))),
        ),
        "article_vocabulary": (
            "article_vocabulary.json",
            _canonical_json(dict(sorted(article_vocabulary.items()))),
        ),
        "catalog_arrays": (
            "catalog_arrays.npz",
            _deterministic_array_archive(
                {
                    "article_ids": np.asarray(article_ids, dtype="U"),
                    "article_vectors": vectors,
                }
            ),
        ),
        "schema": (
            "schema.json",
            _canonical_json(
                {
                    "schema_version": "retrieval-input.v2",
                    "customer_inputs": list(ALLOWED_CUSTOMER_INPUTS),
                    "forbidden_customer_inputs": list(FORBIDDEN_CUSTOMER_INPUTS),
                    "input_signature": executable_input_signature(recent_k),
                }
            ),
        ),
    }
    hashes: dict[str, str] = {}
    for logical_name, (filename, content) in artifacts.items():
        _atomic_write(output / filename, content)
        hashes[logical_name] = _sha256(content)
    checksum_content = "".join(
        f"{hashes[name]}  {name}\n" for name in sorted(hashes)
    ).encode()
    artifacts["checksums"] = ("SHA256SUMS", checksum_content)
    _atomic_write(output / "SHA256SUMS", checksum_content)
    hashes["checksums"] = _sha256(checksum_content)

    artifact_map = {
        name: {"path": artifacts[name][0], "sha256": hashes[name]}
        for name in REQUIRED_ARTIFACTS
    }
    manifest = {
        "schema_version": "retrieval-bundle.v2",
        "bundle_id": bundle_id,
        "data_mode": data_mode,
        "retrieval_fit": ["2018-12-19", "2020-06-30"],
        "retrieval_select": ["2020-07-01", "2020-07-14"],
        "artifact_available_after": "2020-07-14",
        "article_volume": False,
        "embedding": {
            "dimension": training_result.model.dimension,
            "normalization": "recorded_by_model",
            "dtype": "float32",
        },
        "search": {
            "algorithm": "exact_batched_inner_product",
            "score_order": "descending",
            "tie_break": "article_id_ascending",
        },
        "allowed_customer_inputs": list(ALLOWED_CUSTOMER_INPUTS),
        "forbidden_customer_inputs": list(FORBIDDEN_CUSTOMER_INPUTS),
        "required_artifacts": list(REQUIRED_ARTIFACTS),
        "artifacts": artifact_map,
        "input_signature": executable_input_signature(recent_k),
        "code_revision": code_revision,
        "dependency_lock_sha256": dependency_lock_sha256,
    }
    _atomic_write(output / "manifest.json", _canonical_json(manifest))
    load_inference_bundle(output)
    return output
