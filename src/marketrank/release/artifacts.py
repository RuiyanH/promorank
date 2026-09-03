"""Validation and compact sampling of the physical candidate artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
import json
from pathlib import Path
from typing import Mapping

from marketrank.release.core import REQUIRED_SOURCES, ReleaseValidationError
from marketrank.release.core import validate_customer_ref_key


@dataclass(frozen=True)
class ArtifactSnapshot:
    source_dir: Path
    ceiling: dict[str, object]
    source_row_counts: dict[str, int]
    common_customers: tuple[str, ...]


def read_customer_ref_key(path: Path) -> bytes:
    """Read production key material without disclosing its value or location."""
    try:
        key = path.read_bytes()
    except OSError as exc:
        raise ReleaseValidationError("unable to read customer reference key file") from exc
    return validate_customer_ref_key(key)


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseValidationError(f"cannot read JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseValidationError(f"JSON artifact {path} must contain an object")
    return value


def validate_physical_snapshot(source_dir: Path, ceiling_path: Path) -> ArtifactSnapshot:
    """Validate all five complete parquet datasets and their provenance sidecars."""
    try:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.dataset as ds
        import pyarrow.types as pt
    except ImportError as exc:  # pragma: no cover - exercised by packaging, not tests
        raise ReleaseValidationError("pyarrow is required to build a physical release") from exc

    ceiling = _read_json(ceiling_path)
    try:
        expected_as_of = ceiling["run"]["as_of"]  # type: ignore[index]
        expected_sources = set(ceiling["run"]["sources"])  # type: ignore[index]
        expected_stats = ceiling["stats"]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        raise ReleaseValidationError("ceiling JSON has no valid run/stats contract") from exc
    if expected_sources != set(REQUIRED_SOURCES):
        raise ReleaseValidationError("ceiling JSON does not describe the exact five sources")

    row_counts: dict[str, int] = {}
    common_customers: set[str] | None = None
    required_columns = {"customer_id", "article_id", "source", "source_rank"}
    for source in REQUIRED_SOURCES:
        parquet_dir = source_dir / f"{source}.parquet"
        sidecar_path = source_dir / f"{source}.meta.json"
        if not parquet_dir.is_dir() or not (parquet_dir / "_SUCCESS").is_file():
            raise ReleaseValidationError(f"{source} parquet is missing or physically incomplete")
        if not any(p.suffix == ".parquet" and not p.name.startswith(".") for p in parquet_dir.iterdir()):
            raise ReleaseValidationError(f"{source} parquet contains no data parts")
        sidecar = _read_json(sidecar_path)
        if sidecar.get("source") != source or sidecar.get("as_of") != expected_as_of:
            raise ReleaseValidationError(f"{source} sidecar source/as_of is inconsistent")
        if sidecar.get("backfilled") is not True:
            raise ReleaseValidationError(
                f"{source} provenance is not backfilled; v1's historical release contract changed"
            )

        dataset = ds.dataset(parquet_dir, format="parquet", exclude_invalid_files=True)
        if set(dataset.schema.names) != required_columns:
            raise ReleaseValidationError(
                f"{source} parquet columns must be exactly {sorted(required_columns)}"
            )
        if not (
            pt.is_string(dataset.schema.field("customer_id").type)
            and pt.is_string(dataset.schema.field("article_id").type)
            and pt.is_string(dataset.schema.field("source").type)
            and pt.is_integer(dataset.schema.field("source_rank").type)
        ):
            raise ReleaseValidationError(f"{source} parquet has incompatible column types")

        table = dataset.to_table(columns=["customer_id", "article_id", "source", "source_rank"])
        n_rows = table.num_rows
        if n_rows == 0 or any(column.null_count for column in table.columns):
            raise ReleaseValidationError(f"{source} parquet is empty or contains nulls")
        if sidecar.get("rows") != n_rows or expected_stats.get(f"rows_from_{source}") != n_rows:
            raise ReleaseValidationError(f"{source} physical row count does not reconcile")
        if pc.count_distinct(table["source"]).as_py() != 1 or pc.min(table["source"]).as_py() != source:
            raise ReleaseValidationError(f"{source} parquet contains inconsistent source tags")
        if pc.min(table["source_rank"]).as_py() < 1:
            raise ReleaseValidationError(f"{source} parquet contains a non-positive source rank")
        valid_articles = pc.match_substring_regex(table["article_id"], r"^[0-9]{10}$")
        if pc.all(valid_articles).as_py() is not True:
            raise ReleaseValidationError(f"{source} parquet contains an invalid article ID")
        if table.select(["customer_id", "article_id"]).group_by(
            ["customer_id", "article_id"]
        ).aggregate([]).num_rows != n_rows:
            raise ReleaseValidationError(f"{source} repeats a customer/article contribution")
        if table.select(["customer_id", "source_rank"]).group_by(
            ["customer_id", "source_rank"]
        ).aggregate([]).num_rows != n_rows:
            raise ReleaseValidationError(f"{source} repeats a customer/source rank")

        customers = set(pc.unique(table["customer_id"]).to_pylist())
        if "" in customers:
            raise ReleaseValidationError(f"{source} contains an empty customer ID")
        common_customers = customers if common_customers is None else common_customers & customers
        row_counts[source] = n_rows

    if not common_customers:
        raise ReleaseValidationError("the five candidate sources have no customers in common")
    return ArtifactSnapshot(
        source_dir=source_dir,
        ceiling=ceiling,
        source_row_counts=row_counts,
        common_customers=tuple(sorted(common_customers)),
    )


def select_demo_customers(snapshot: ArtifactSnapshot, release_id: str, count: int) -> tuple[str, ...]:
    """Select a deterministic, source-complete sample without exposing IDs."""
    if count < 1 or count > len(snapshot.common_customers):
        raise ReleaseValidationError("demo customer count is outside the source-complete cohort")
    return tuple(
        sorted(
            snapshot.common_customers,
            key=lambda customer_id: (
                hashlib.sha256(f"{release_id}\0{customer_id}".encode()).digest(),
                customer_id,
            ),
        )[:count]
    )


def load_sample_rows(
    snapshot: ArtifactSnapshot, customer_ids: tuple[str, ...]
) -> dict[str, list[dict[str, object]]]:
    """Read only selected customer rows after the full snapshot has passed validation."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.dataset as ds

    selected = pa.array(customer_ids)
    sources: dict[str, list[dict[str, object]]] = {}
    for source in REQUIRED_SOURCES:
        table = ds.dataset(
            snapshot.source_dir / f"{source}.parquet",
            format="parquet",
            exclude_invalid_files=True,
        ).to_table(columns=["customer_id", "article_id", "source", "source_rank"])
        sample = table.filter(pc.is_in(table["customer_id"], value_set=selected))
        sources[source] = sample.to_pylist()
    return sources


_METADATA_COLUMNS = {
    "product_name": "prod_name",
    "product_type_name": "product_type_name",
    "colour_group_name": "colour_group_name",
    "department_name": "department_name",
    "index_group_name": "index_group_name",
    "garment_group_name": "garment_group_name",
}


def load_article_metadata(
    csv_path: Path, article_ids: set[str]
) -> dict[str, dict[str, str]]:
    """Load the six explicitly allowed display fields for selected articles."""
    found: dict[str, dict[str, str]] = {}
    try:
        handle = csv_path.open(encoding="utf-8", newline="")
    except OSError as exc:
        raise ReleaseValidationError(f"cannot read article metadata {csv_path}: {exc}") from exc
    with handle:
        reader = csv.DictReader(handle)
        required = {"article_id", *_METADATA_COLUMNS.values()}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ReleaseValidationError("article metadata CSV is missing required display columns")
        for row in reader:
            article_id = row["article_id"]
            if article_id in article_ids:
                found[article_id] = {
                    output: row[input_name] or "Unknown"
                    for output, input_name in _METADATA_COLUMNS.items()
                }
    missing = sorted(article_ids - set(found))
    if missing:
        raise ReleaseValidationError(
            f"article metadata is missing {len(missing)} selected IDs, first={missing[:3]}"
        )
    return found


def find_default_articles(repo_root: Path) -> Path:
    """Find the complete local source CSV; never silently use the tiny CI seed."""
    candidates = (
        repo_root / "data/raw/articles.csv",
        repo_root.parent / "marketrank/data/raw/articles.csv",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise ReleaseValidationError(
        "complete articles.csv not found; pass --articles (the 47-row CI seed is insufficient)"
    )
