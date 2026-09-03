"""Checksum-complete, deterministic daily embedding-retrieval partitions."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from marketrank.candidate_pipeline.guards import assert_large_output_path
from marketrank.candidate_pipeline.privacy import (
    CustomerIdentifierError,
    validate_customer_identifier,
)
from marketrank.retrieval.inference_bundle import ALLOWED_DATA_MODES, InferenceBundleManifest

SCHEMA_VERSION = "daily-ann.v2"
RECORDS_FILE = "records.jsonl"
MANIFEST_FILE = "manifest.json"
SUCCESS_FILE = "_SUCCESS"
ROW_KEYS = ("customer_id", "day_index", "article_id", "source", "source_rank")
SPINE_TYPES = frozenset({"active_day", "replay_day"})
DAY_ZERO = dt.date(2018, 9, 20)
FORBIDDEN_FIELDS = frozenset(
    {
        "raw_customer_id",
        "customer_key_mapping",
        "label",
        "truth_articles",
        "age",
        "age_bucket",
        "club_member_status",
        "fashion_news_frequency",
        "fn",
        "active",
    }
)


class DailyAnnError(ValueError):
    """A daily ANN partition is partial, corrupt, or cross-version."""


def partition_path(root: str | Path, scoring_date: str) -> Path:
    _parse_date(scoring_date, "scoring_date")
    return Path(root) / f"scoring_date={scoring_date}"


def _parse_date(value: object, where: str) -> dt.date:
    if not isinstance(value, str):
        raise DailyAnnError(f"{where} must be an ISO date string")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise DailyAnnError(f"{where} must be an ISO date string") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def _validate_rows(rows: Iterable[Mapping[str, Any]], *, day_index: int, depth: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen_articles: set[tuple[str, str]] = set()
    ranks_by_customer: dict[str, list[int]] = {}
    for raw in rows:
        if set(raw) != set(ROW_KEYS):
            raise DailyAnnError(
                f"ANN row keys mismatch; expected={list(ROW_KEYS)}, got={sorted(raw)}"
            )
        if set(raw) & FORBIDDEN_FIELDS:
            raise DailyAnnError("ANN rows contain a forbidden private or outcome field")
        customer = raw["customer_id"]
        article = raw["article_id"]
        rank = raw["source_rank"]
        try:
            validate_customer_identifier(customer)
        except CustomerIdentifierError as exc:
            raise DailyAnnError(str(exc)) from exc
        if not isinstance(article, str) or not article:
            raise DailyAnnError("article_id must be a non-empty string")
        if raw["day_index"] != day_index:
            raise DailyAnnError("ANN row day_index does not match partition metadata")
        if raw["source"] != "ann":
            raise DailyAnnError("daily retrieval source must be ann")
        if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= depth:
            raise DailyAnnError("source_rank is outside the configured ANN depth")
        if (customer, article) in seen_articles:
            raise DailyAnnError(f"duplicate ANN customer/article row: {customer}/{article}")
        seen_articles.add((customer, article))
        ranks_by_customer.setdefault(customer, []).append(rank)
        output.append({key: raw[key] for key in ROW_KEYS})
    for customer, ranks in ranks_by_customer.items():
        ordered = sorted(ranks)
        if ordered != list(range(1, len(ordered) + 1)):
            raise DailyAnnError(f"ANN ranks for {customer} are not unique and contiguous from 1")
    return sorted(output, key=lambda row: (row["customer_id"], row["source_rank"], row["article_id"]))


def _records_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(_canonical_json(row) for row in rows)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def write_daily_ann_partition(
    root: str | Path,
    *,
    scoring_date: str,
    day_index: int,
    bundle_id: str,
    candidate_config_id: str,
    cohort_id: str,
    spine_type: str,
    depth: int,
    eligible_article_count: int,
    rows: Iterable[Mapping[str, Any]],
    data_mode: str = "synthetic_fixture",
    input_hashes: Mapping[str, str],
    verified_bundle: InferenceBundleManifest | None = None,
    large_mode: bool = False,
    scratch_root: str | Path | None = None,
) -> dict[str, Any]:
    """Write or safely reuse one daily partition, committing its marker last."""

    score_day = _parse_date(scoring_date, "scoring_date")
    if data_mode not in ALLOWED_DATA_MODES:
        raise DailyAnnError(f"unsupported data_mode: {data_mode}")
    if data_mode != "synthetic_fixture":
        if (
            verified_bundle is None
            or not verified_bundle.complete
            or verified_bundle.data_mode != data_mode
            or verified_bundle.bundle_id != bundle_id
        ):
            raise DailyAnnError("non-synthetic daily output requires its complete verified bundle")
    if set(input_hashes) != {"catalog", "queries", "article_first_seen"}:
        raise DailyAnnError("input_hashes must bind catalog, queries, and article_first_seen")
    if any(
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        for digest in input_hashes.values()
    ):
        raise DailyAnnError("input_hashes must be lowercase SHA-256 digests")
    if spine_type not in SPINE_TYPES:
        raise DailyAnnError(f"invalid spine_type: {spine_type!r}")
    for name, value in {
        "bundle_id": bundle_id,
        "candidate_config_id": candidate_config_id,
        "cohort_id": cohort_id,
    }.items():
        if not isinstance(value, str) or not value:
            raise DailyAnnError(f"{name} must be a non-empty string")
    if isinstance(day_index, bool) or not isinstance(day_index, int) or day_index < 0:
        raise DailyAnnError("day_index must be a non-negative integer")
    if (score_day - DAY_ZERO).days != day_index:
        raise DailyAnnError("day_index does not match scoring_date relative to the dataset epoch")
    if isinstance(depth, bool) or not isinstance(depth, int) or depth <= 0:
        raise DailyAnnError("depth must be a positive integer")
    if (
        isinstance(eligible_article_count, bool)
        or not isinstance(eligible_article_count, int)
        or eligible_article_count < 0
    ):
        raise DailyAnnError("eligible_article_count must be a non-negative integer")
    root_path = Path(root).expanduser().resolve()
    if large_mode:
        if scratch_root is None:
            raise DailyAnnError("large_mode requires an explicit scratch_root")
        assert_large_output_path(root_path, scratch_root)

    checked_rows = _validate_rows(rows, day_index=day_index, depth=depth)
    unique_articles = {row["article_id"] for row in checked_rows}
    if len(unique_articles) > eligible_article_count:
        raise DailyAnnError("ANN rows exceed the declared eligible article catalog")
    counts_by_customer: dict[str, int] = {}
    for row in checked_rows:
        counts_by_customer[row["customer_id"]] = counts_by_customer.get(row["customer_id"], 0) + 1
    maximum_rows = min(depth, eligible_article_count)
    if any(count > maximum_rows for count in counts_by_customer.values()):
        raise DailyAnnError("ANN customer rows exceed depth or eligible catalog exhaustion")
    payload = _records_bytes(checked_rows)
    payload_hash = _sha256_bytes(payload)
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "data_mode": data_mode,
        "scoring_date": scoring_date,
        "day_index": day_index,
        "bundle_id": bundle_id,
        "candidate_config_id": candidate_config_id,
        "cohort_id": cohort_id,
        "spine_type": spine_type,
        "source": "ann",
        "depth": depth,
        "eligible_article_count": eligible_article_count,
        "row_count": len(checked_rows),
        "customer_count": len({row["customer_id"] for row in checked_rows}),
        "files": {RECORDS_FILE: payload_hash},
        "partition_checksum": payload_hash,
        "input_hashes": dict(sorted(input_hashes.items())),
    }
    part = partition_path(root_path, scoring_date)
    if all((part / name).is_file() for name in (SUCCESS_FILE, MANIFEST_FILE, RECORDS_FILE)):
        existing = read_daily_ann_partition(
            root_path,
            scoring_date,
            expected={
                "day_index": day_index,
                "bundle_id": bundle_id,
                "candidate_config_id": candidate_config_id,
                "cohort_id": cohort_id,
                "spine_type": spine_type,
                "depth": depth,
                "data_mode": data_mode,
            },
        )
        if existing["manifest"] != manifest or existing["rows"] != checked_rows:
            raise DailyAnnError("complete partition exists with different content or metadata")
        return {"state": "reused", "path": str(part), "manifest": manifest}

    part.mkdir(parents=True, exist_ok=True)
    _atomic_write(part / RECORDS_FILE, payload)
    _atomic_write(part / MANIFEST_FILE, _canonical_json(manifest))
    _atomic_write(part / SUCCESS_FILE, b"")
    return {"state": "written", "path": str(part), "manifest": manifest}


def validate_daily_ann_manifest(
    root: str | Path,
    scoring_date: str,
    *,
    expected: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate identity and payload checksum without retaining partition rows."""

    _parse_date(scoring_date, "scoring_date")
    part = partition_path(root, scoring_date)
    for name in (SUCCESS_FILE, MANIFEST_FILE, RECORDS_FILE):
        if not (part / name).is_file():
            raise DailyAnnError(f"daily ANN partition is incomplete: missing {name}")
    unexpected = sorted(
        item.name for item in part.iterdir() if item.name not in {SUCCESS_FILE, MANIFEST_FILE, RECORDS_FILE}
    )
    if unexpected:
        raise DailyAnnError(f"daily ANN partition contains unmanifested files: {unexpected}")
    try:
        manifest = json.loads((part / MANIFEST_FILE).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DailyAnnError("daily ANN manifest is invalid JSON") from exc
    required_manifest_keys = {
        "schema_version",
        "data_mode",
        "scoring_date",
        "day_index",
        "bundle_id",
        "candidate_config_id",
        "cohort_id",
        "spine_type",
        "source",
        "depth",
        "eligible_article_count",
        "row_count",
        "customer_count",
        "files",
        "partition_checksum",
        "input_hashes",
    }
    if set(manifest) != required_manifest_keys:
        raise DailyAnnError("daily ANN manifest keys mismatch")
    if set(manifest) & FORBIDDEN_FIELDS:
        raise DailyAnnError("daily ANN manifest contains a forbidden field")
    if manifest["schema_version"] != SCHEMA_VERSION or manifest["data_mode"] not in ALLOWED_DATA_MODES:
        raise DailyAnnError("daily ANN schema or data mode mismatch")
    for name in ("bundle_id", "candidate_config_id", "cohort_id"):
        if not isinstance(manifest[name], str) or not manifest[name]:
            raise DailyAnnError(f"daily ANN {name} must be a non-empty string")
    if set(manifest["input_hashes"]) != {"catalog", "queries", "article_first_seen"}:
        raise DailyAnnError("daily ANN input hash identity is incomplete")
    if any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in manifest["input_hashes"].values()
    ):
        raise DailyAnnError("daily ANN input hashes are not lowercase SHA-256 digests")
    if manifest["scoring_date"] != scoring_date:
        raise DailyAnnError("daily ANN directory date and manifest date differ")
    if manifest["source"] != "ann" or manifest["spine_type"] not in SPINE_TYPES:
        raise DailyAnnError("daily ANN source or spine_type is invalid")
    for name, minimum in (("day_index", 0), ("eligible_article_count", 0), ("row_count", 0), ("customer_count", 0)):
        value = manifest[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise DailyAnnError(f"daily ANN {name} must be an integer >= {minimum}")
    if isinstance(manifest["depth"], bool) or not isinstance(manifest["depth"], int) or manifest["depth"] <= 0:
        raise DailyAnnError("daily ANN depth must be a positive integer")
    if (_parse_date(scoring_date, "scoring_date") - DAY_ZERO).days != manifest["day_index"]:
        raise DailyAnnError("daily ANN day_index does not match scoring_date")
    if (
        not isinstance(manifest["partition_checksum"], str)
        or len(manifest["partition_checksum"]) != 64
        or any(character not in "0123456789abcdef" for character in manifest["partition_checksum"])
    ):
        raise DailyAnnError("daily ANN partition checksum is not a lowercase SHA-256 digest")
    if manifest["files"] != {RECORDS_FILE: manifest["partition_checksum"]}:
        raise DailyAnnError("daily ANN file checksum manifest is incomplete")
    digest = hashlib.sha256()
    with (part / RECORDS_FILE).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != manifest["partition_checksum"]:
        raise DailyAnnError("daily ANN records checksum mismatch")
    if expected:
        unknown = sorted(set(expected) - required_manifest_keys)
        if unknown:
            raise DailyAnnError(f"unknown expected metadata keys: {unknown}")
        for key, value in expected.items():
            if manifest[key] != value:
                raise DailyAnnError(f"daily ANN {key} mismatch: {manifest[key]!r} != {value!r}")
    return manifest


def read_daily_ann_partition(
    root: str | Path,
    scoring_date: str,
    *,
    expected: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read one partition only after marker, schema, and checksum validation."""

    part = partition_path(root, scoring_date)
    manifest = validate_daily_ann_manifest(root, scoring_date, expected=expected)
    payload = (part / RECORDS_FILE).read_bytes()
    rows: list[dict[str, Any]] = []
    try:
        for line in payload.splitlines():
            if line:
                rows.append(json.loads(line))
    except json.JSONDecodeError as exc:
        raise DailyAnnError("daily ANN records contain invalid JSON") from exc
    rows = _validate_rows(rows, day_index=manifest["day_index"], depth=manifest["depth"])
    if len(rows) != manifest["row_count"]:
        raise DailyAnnError("daily ANN row_count mismatch")
    if len({row["customer_id"] for row in rows}) != manifest["customer_count"]:
        raise DailyAnnError("daily ANN customer_count mismatch")
    if len({row["article_id"] for row in rows}) > manifest["eligible_article_count"]:
        raise DailyAnnError("daily ANN rows exceed eligible_article_count")
    maximum_rows = min(manifest["depth"], manifest["eligible_article_count"])
    counts_by_customer: dict[str, int] = {}
    for row in rows:
        counts_by_customer[row["customer_id"]] = counts_by_customer.get(row["customer_id"], 0) + 1
    if any(count > maximum_rows for count in counts_by_customer.values()):
        raise DailyAnnError("daily ANN customer rows exceed depth or eligible catalog exhaustion")
    return {"manifest": manifest, "rows": rows, "path": str(part)}


def read_daily_ann_range(
    root: str | Path,
    scoring_dates: Iterable[str],
    *,
    expected: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read exact requested dates and reject duplicate or missing partitions."""

    dates = list(scoring_dates)
    if len(set(dates)) != len(dates):
        raise DailyAnnError("duplicate scoring dates requested")
    partitions = []
    rows = []
    for date in dates:
        result = read_daily_ann_partition(root, date, expected=expected)
        partitions.append(result["manifest"])
        rows.extend(result["rows"])
    _assert_range_invariants(partitions)
    return {"partitions": partitions, "rows": rows}


def _assert_range_invariants(partitions: list[Mapping[str, Any]]) -> None:
    if not partitions:
        return
    invariant_fields = (
        "bundle_id",
        "candidate_config_id",
        "cohort_id",
        "spine_type",
        "depth",
        "data_mode",
    )
    reference = partitions[0]
    for manifest in partitions[1:]:
        mismatched = [key for key in invariant_fields if manifest[key] != reference[key]]
        if mismatched:
            raise DailyAnnError(f"daily ANN range mixes partition metadata fields: {mismatched}")


def validate_daily_ann_range(
    root: str | Path,
    scoring_dates: Iterable[str],
    *,
    expected: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Validate all requested manifests/checksums without loading their rows."""

    dates = list(scoring_dates)
    if not dates or len(set(dates)) != len(dates):
        raise DailyAnnError("scoring dates must be a non-empty unique sequence")
    manifests = [validate_daily_ann_manifest(root, date, expected=expected) for date in dates]
    _assert_range_invariants(manifests)
    return manifests
