"""Strict V2 inference-bundle manifest and content-checksum validation."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from marketrank.candidate_pipeline.privacy import (
    CustomerIdentifierError,
    validate_customer_identifier,
)

SCHEMA_VERSION = "retrieval-bundle.v2"
ALLOWED_DATA_MODES = frozenset({"synthetic_fixture", "non_release_pilot"})
ALLOWED_CUSTOMER_INPUTS = (
    "customer_id_embedding",
    "recent_article_sequence",
    "days_since_last_purchase",
    "purchase_count_7d",
    "purchase_count_30d",
    "purchase_count_90d",
)
FORBIDDEN_CUSTOMER_INPUTS = (
    "age",
    "age_bucket",
    "club_member_status",
    "fashion_news_frequency",
    "fn",
    "active",
)
REQUIRED_ARTIFACTS = (
    "model_weights",
    "training_arguments",
    "metrics",
    "customer_vocabulary",
    "article_vocabulary",
    "catalog_arrays",
    "schema",
    "checksums",
)
JSON_ARTIFACTS = frozenset(
    {"training_arguments", "metrics", "customer_vocabulary", "article_vocabulary", "schema"}
)
_TOP_LEVEL_KEYS = {
    "schema_version",
    "bundle_id",
    "data_mode",
    "retrieval_fit",
    "retrieval_select",
    "artifact_available_after",
    "article_volume",
    "embedding",
    "search",
    "allowed_customer_inputs",
    "forbidden_customer_inputs",
    "required_artifacts",
}
_OPTIONAL_TOP_LEVEL_KEYS = {"artifacts", "input_signature", "code_revision", "dependency_lock_sha256"}


class InferenceBundleError(ValueError):
    """An inference bundle is incomplete, unsafe, or cross-version."""


def _date(value: object, where: str) -> dt.date:
    if not isinstance(value, str):
        raise InferenceBundleError(f"{where} must be an ISO date string")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise InferenceBundleError(f"{where} must be an ISO date string") from exc


def _date_range(value: object, where: str) -> tuple[dt.date, dt.date]:
    if not isinstance(value, list) or len(value) != 2:
        raise InferenceBundleError(f"{where} must contain [start, end]")
    start, end = (_date(value[0], where), _date(value[1], where))
    if start > end:
        raise InferenceBundleError(f"{where} start must not follow its end")
    return start, end


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _forbidden_tokens(value: Any, *, under_declaration: bool = False) -> set[str]:
    found: set[str] = set()
    forbidden = set(FORBIDDEN_CUSTOMER_INPUTS)
    if isinstance(value, Mapping):
        for key, child in value.items():
            declaration = under_declaration or key == "forbidden_customer_inputs"
            if not declaration and str(key).lower() in forbidden:
                found.add(str(key).lower())
            found |= _forbidden_tokens(child, under_declaration=declaration)
    elif isinstance(value, list):
        for child in value:
            found |= _forbidden_tokens(child, under_declaration=under_declaration)
    elif isinstance(value, str) and not under_declaration and value.lower() in forbidden:
        found.add(value.lower())
    return found


def _unknown_customer_inputs(value: Any) -> set[str]:
    """Find executable customer-input declarations outside the allowlist."""

    unknown: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in {"customer_inputs", "customer_features"}:
                if not isinstance(child, list) or any(not isinstance(item, str) for item in child):
                    unknown.add("<invalid-customer-input-declaration>")
                else:
                    unknown |= set(child) - set(ALLOWED_CUSTOMER_INPUTS)
            else:
                unknown |= _unknown_customer_inputs(child)
    elif isinstance(value, list):
        for child in value:
            unknown |= _unknown_customer_inputs(child)
    return unknown


def _validate_executable_signature(signature: object) -> None:
    if not isinstance(signature, Mapping) or set(signature) != {
        "customer_inputs",
        "tensor_inputs",
        "article_inputs",
        "output_dtype",
    }:
        raise InferenceBundleError("complete bundle input_signature keys mismatch")
    if signature["customer_inputs"] != list(ALLOWED_CUSTOMER_INPUTS):
        raise InferenceBundleError("complete bundle input_signature must bind all PIT-safe customer inputs")
    tensor_inputs = signature["tensor_inputs"]
    if not isinstance(tensor_inputs, Mapping) or set(tensor_inputs) != {
        "customer_indices",
        "recent_article_indices",
        "numeric_features",
    }:
        raise InferenceBundleError("complete bundle tensor input signature keys mismatch")
    if tensor_inputs["customer_indices"] != {"dtype": "int64", "rank": 1}:
        raise InferenceBundleError("customer_indices signature mismatch")
    recent = tensor_inputs["recent_article_indices"]
    if (
        not isinstance(recent, Mapping)
        or set(recent) != {"dtype", "rank", "width"}
        or recent.get("dtype") != "int64"
        or recent.get("rank") != 2
        or isinstance(recent.get("width"), bool)
        or not isinstance(recent.get("width"), int)
        or recent["width"] <= 0
    ):
        raise InferenceBundleError("recent_article_indices signature mismatch")
    if tensor_inputs["numeric_features"] != {"dtype": "float32", "rank": 2, "width": 4}:
        raise InferenceBundleError("numeric_features signature mismatch")
    if signature["article_inputs"] != ["article_id_embedding"]:
        raise InferenceBundleError("article input signature mismatch")
    if signature["output_dtype"] != "float32":
        raise InferenceBundleError("complete bundle input_signature output must be float32")


@dataclass(frozen=True)
class InferenceBundleManifest:
    _raw_json: str
    manifest_path: Path
    complete: bool = False
    _artifact_paths: tuple[tuple[str, str], ...] = ()

    @property
    def raw(self) -> dict[str, Any]:
        """Return a detached copy so runtime code cannot mutate bundle identity."""

        return json.loads(self._raw_json)

    @property
    def bundle_id(self) -> str:
        return str(self.raw["bundle_id"])

    @property
    def dimension(self) -> int:
        return int(self.raw["embedding"]["dimension"])

    @property
    def data_mode(self) -> str:
        return str(self.raw["data_mode"])

    def artifact_path(self, logical_name: str) -> Path:
        paths = dict(self._artifact_paths)
        if logical_name not in paths:
            raise InferenceBundleError(f"bundle has no verified artifact path for {logical_name}")
        return Path(paths[logical_name])

    @property
    def available_after(self) -> dt.date:
        return _date(self.raw["artifact_available_after"], "artifact_available_after")

    def assert_scoring_date(self, scoring_date: str) -> None:
        day = _date(scoring_date, "scoring_date")
        if day <= self.available_after:
            raise InferenceBundleError(
                f"bundle {self.bundle_id} is available only after {self.available_after.isoformat()}"
            )

    def as_dict(self) -> dict[str, Any]:
        return self.raw


def validate_inference_bundle_manifest(
    value: Mapping[str, Any], *, manifest_path: str | Path = "<memory>"
) -> InferenceBundleManifest:
    if not isinstance(value, Mapping):
        raise InferenceBundleError("bundle manifest must be a JSON object")
    keys = set(value)
    missing = sorted(_TOP_LEVEL_KEYS - keys)
    extra = sorted(keys - _TOP_LEVEL_KEYS - _OPTIONAL_TOP_LEVEL_KEYS)
    if missing or extra:
        raise InferenceBundleError(f"bundle manifest keys mismatch; missing={missing}, extra={extra}")
    if value["schema_version"] != SCHEMA_VERSION:
        raise InferenceBundleError(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(value["bundle_id"], str) or not value["bundle_id"].startswith("v2_pit_safe"):
        raise InferenceBundleError("bundle_id must identify the v2_pit_safe family")
    if value["data_mode"] not in ALLOWED_DATA_MODES:
        raise InferenceBundleError(
            f"data_mode must be one of {sorted(ALLOWED_DATA_MODES)}"
        )
    fit_start, fit_end = _date_range(value["retrieval_fit"], "retrieval_fit")
    select_start, select_end = _date_range(value["retrieval_select"], "retrieval_select")
    if (fit_start.isoformat(), fit_end.isoformat()) != ("2018-12-19", "2020-06-30"):
        raise InferenceBundleError("retrieval_fit does not match the frozen nested chronology")
    if (select_start.isoformat(), select_end.isoformat()) != ("2020-07-01", "2020-07-14"):
        raise InferenceBundleError("retrieval_select does not match the frozen nested chronology")
    if fit_end >= select_start:
        raise InferenceBundleError("retrieval_fit and retrieval_select overlap or are reordered")
    available_after = _date(value["artifact_available_after"], "artifact_available_after")
    if available_after != select_end:
        raise InferenceBundleError("artifact_available_after must equal retrieval_select end")
    if value["article_volume"] is not False:
        raise InferenceBundleError("primary V2 retrieval forbids time-varying article_volume")

    embedding = value["embedding"]
    if not isinstance(embedding, Mapping) or set(embedding) != {"dimension", "normalization", "dtype"}:
        raise InferenceBundleError("embedding contract keys mismatch")
    if isinstance(embedding["dimension"], bool) or not isinstance(embedding["dimension"], int) or embedding["dimension"] <= 0:
        raise InferenceBundleError("embedding.dimension must be a positive integer")
    if embedding["normalization"] != "recorded_by_model" or embedding["dtype"] != "float32":
        raise InferenceBundleError("embedding normalization/dtype contract mismatch")
    search = value["search"]
    if search != {
        "algorithm": "exact_batched_inner_product",
        "score_order": "descending",
        "tie_break": "article_id_ascending",
    }:
        raise InferenceBundleError("search must be exact float32 inner product with the frozen ordering")
    if value["allowed_customer_inputs"] != list(ALLOWED_CUSTOMER_INPUTS):
        raise InferenceBundleError("allowed_customer_inputs do not match the PIT-safe primary contract")
    if value["forbidden_customer_inputs"] != list(FORBIDDEN_CUSTOMER_INPUTS):
        raise InferenceBundleError("forbidden_customer_inputs do not match the frozen contract")
    if value["required_artifacts"] != list(REQUIRED_ARTIFACTS):
        raise InferenceBundleError("required_artifacts do not match the frozen contract")
    unsafe = _forbidden_tokens({k: v for k, v in value.items() if k != "forbidden_customer_inputs"})
    if unsafe:
        raise InferenceBundleError(f"mutable customer fields appear in executable bundle metadata: {sorted(unsafe)}")
    unknown = _unknown_customer_inputs(value.get("input_signature", {}))
    if unknown:
        raise InferenceBundleError(f"customer input signature is outside the allowlist: {sorted(unknown)}")
    return InferenceBundleManifest(
        json.dumps(value, sort_keys=True, separators=(",", ":")), Path(manifest_path)
    )


def read_inference_bundle_manifest(path: str | Path) -> InferenceBundleManifest:
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InferenceBundleError(f"cannot read bundle manifest {path}: {exc}") from exc
    return validate_inference_bundle_manifest(value, manifest_path=path)


def load_inference_bundle(path: str | Path) -> InferenceBundleManifest:
    """Load a checksum-complete bundle directory.

    Passing a manifest file validates the frozen schema only. Passing a
    directory additionally requires and verifies every physical artifact.
    """

    path = Path(path)
    if path.is_file():
        return read_inference_bundle_manifest(path)
    manifest_path = path / "manifest.json"
    manifest = read_inference_bundle_manifest(manifest_path)
    artifacts = manifest.raw.get("artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != set(REQUIRED_ARTIFACTS):
        raise InferenceBundleError("bundle directory must map every required artifact")
    if "input_signature" not in manifest.raw:
        raise InferenceBundleError("complete bundle requires an executable input_signature")
    signature = manifest.raw["input_signature"]
    _validate_executable_signature(signature)
    verified_paths: list[tuple[str, str]] = []
    for logical_name in REQUIRED_ARTIFACTS:
        spec = artifacts[logical_name]
        if not isinstance(spec, Mapping) or set(spec) != {"path", "sha256"}:
            raise InferenceBundleError(f"artifact {logical_name} must declare path and sha256")
        relative = Path(spec["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise InferenceBundleError(f"artifact {logical_name} path escapes the bundle")
        unresolved_artifact_path = path / relative
        artifact_path = unresolved_artifact_path.resolve()
        try:
            artifact_path.relative_to(path.resolve())
        except ValueError as exc:
            raise InferenceBundleError(f"artifact {logical_name} path escapes the bundle") from exc
        if unresolved_artifact_path.is_symlink() or not artifact_path.is_file():
            raise InferenceBundleError(f"artifact {logical_name} is missing or is not a regular file")
        expected = spec["sha256"]
        if not isinstance(expected, str) or len(expected) != 64 or _sha256(artifact_path) != expected:
            raise InferenceBundleError(f"artifact {logical_name} checksum mismatch")
        if logical_name in JSON_ARTIFACTS:
            try:
                content = json.loads(artifact_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise InferenceBundleError(f"artifact {logical_name} is invalid JSON") from exc
            unsafe = _forbidden_tokens(content)
            if unsafe:
                raise InferenceBundleError(
                    f"mutable customer fields appear in {logical_name}: {sorted(unsafe)}"
                )
            unknown = _unknown_customer_inputs(content)
            if unknown:
                raise InferenceBundleError(
                    f"customer inputs in {logical_name} are outside the allowlist: {sorted(unknown)}"
                )
            if logical_name == "customer_vocabulary":
                if not isinstance(content, Mapping):
                    raise InferenceBundleError("customer_vocabulary must be a JSON object")
                try:
                    for customer_id in content:
                        validate_customer_identifier(customer_id)
                except CustomerIdentifierError as exc:
                    raise InferenceBundleError(str(exc)) from exc
        if logical_name == "catalog_arrays":
            try:
                import numpy as np

                with np.load(artifact_path, allow_pickle=False) as catalog:
                    if set(catalog.files) != {"article_ids", "article_vectors"}:
                        raise InferenceBundleError("catalog_arrays members mismatch")
                    if catalog["article_ids"].ndim != 1 or catalog["article_ids"].dtype.kind not in {"U", "S"}:
                        raise InferenceBundleError("catalog article_ids must be a string array")
                    if catalog["article_vectors"].ndim != 2 or catalog["article_vectors"].dtype.name != "float32":
                        raise InferenceBundleError("catalog article_vectors must be rank-2 float32")
            except (OSError, ValueError) as exc:
                raise InferenceBundleError("catalog_arrays is not a valid safe NPZ") from exc
        verified_paths.append((logical_name, str(artifact_path)))

    checksum_path = Path(dict(verified_paths)["checksums"])
    declared_checksums: dict[str, str] = {}
    try:
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            digest, logical_name = line.split("  ", 1)
            declared_checksums[logical_name] = digest
    except (OSError, ValueError) as exc:
        raise InferenceBundleError("checksums artifact has invalid syntax") from exc
    expected_names = set(REQUIRED_ARTIFACTS) - {"checksums"}
    if set(declared_checksums) != expected_names:
        raise InferenceBundleError("checksums artifact does not cover every non-self artifact")
    for logical_name in expected_names:
        if declared_checksums[logical_name] != artifacts[logical_name]["sha256"]:
            raise InferenceBundleError(f"checksums artifact disagrees for {logical_name}")
    return InferenceBundleManifest(
        manifest._raw_json,
        manifest.manifest_path,
        complete=True,
        _artifact_paths=tuple(sorted(verified_paths)),
    )
