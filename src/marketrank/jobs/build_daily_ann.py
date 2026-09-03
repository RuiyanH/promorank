"""Build one synthetic, checksum-complete V2 daily retrieval partition.

A0 supports only synthetic fixtures. Real retriever training and the seven-day
pilot remain integrator-owned G0b work.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from marketrank.candidate_pipeline.config import CandidateConfig, load_candidate_config
from marketrank.retrieval.daily_ann import write_daily_ann_partition
from marketrank.retrieval.inference_bundle import InferenceBundleManifest, load_inference_bundle
from marketrank.retrieval_v2.exact import exact_daily_retrieval


def build_daily_partition(
    *,
    bundle: InferenceBundleManifest,
    config: CandidateConfig,
    article_ids: Sequence[str],
    article_vectors: object,
    article_first_seen: Mapping[str, str],
    customer_ids: Sequence[str],
    customer_vectors: object,
    scoring_date: str,
    day_index: int,
    cohort_id: str,
    spine_type: str,
    out_root: str | Path,
    batch_size: int = 512,
    large_mode: bool = False,
    scratch_root: str | Path | None = None,
    catalog_sha256: str | None = None,
    query_sha256: str | None = None,
    first_seen_sha256: str | None = None,
) -> dict[str, Any]:
    """Run exact retrieval and atomically write its daily partition."""

    bundle.assert_scoring_date(scoring_date)
    if bundle.data_mode != "synthetic_fixture" and not bundle.complete:
        raise ValueError("non-synthetic daily retrieval requires a complete verified bundle directory")
    article_matrix = np.asarray(article_vectors)
    customer_matrix = np.asarray(customer_vectors)
    if article_matrix.dtype != np.dtype(np.float32) or customer_matrix.dtype != np.dtype(np.float32):
        raise ValueError("article and customer vectors must already have dtype float32")
    if article_matrix.ndim != 2 or article_matrix.shape[1] != bundle.dimension:
        raise ValueError("article_vectors do not match the bundle embedding dimension")
    if customer_matrix.ndim != 2 or customer_matrix.shape[1] != bundle.dimension:
        raise ValueError("customer_vectors do not match the bundle embedding dimension")
    depth = config.depth("ann")
    rows = exact_daily_retrieval(
        article_ids=article_ids,
        article_vectors=article_matrix,
        customer_ids=customer_ids,
        customer_vectors=customer_matrix,
        article_first_seen=article_first_seen,
        scoring_date=scoring_date,
        day_index=day_index,
        depth=depth,
        batch_size=batch_size,
    )
    try:
        score_day = dt.date.fromisoformat(scoring_date)
        eligible_count = sum(dt.date.fromisoformat(date) < score_day for date in article_first_seen.values())
    except (TypeError, ValueError) as exc:
        raise ValueError("article first-seen values must be ISO dates") from exc
    catalog_sha256 = catalog_sha256 or _hash_array_inputs(article_ids, article_matrix)
    query_sha256 = query_sha256 or _hash_array_inputs(customer_ids, customer_matrix)
    first_seen_sha256 = first_seen_sha256 or hashlib.sha256(
        _canonical_json(dict(sorted(article_first_seen.items())))
    ).hexdigest()
    if bundle.complete:
        expected_catalog_hash = bundle.raw["artifacts"]["catalog_arrays"]["sha256"]
        if catalog_sha256 != expected_catalog_hash:
            raise ValueError("catalog input does not match the verified bundle catalog_arrays artifact")
    return write_daily_ann_partition(
        out_root,
        scoring_date=scoring_date,
        day_index=day_index,
        bundle_id=bundle.bundle_id,
        candidate_config_id=config.candidate_config_id,
        cohort_id=cohort_id,
        spine_type=spine_type,
        depth=depth,
        eligible_article_count=eligible_count,
        rows=rows,
        data_mode=bundle.data_mode,
        input_hashes={
            "catalog": catalog_sha256,
            "queries": query_sha256,
            "article_first_seen": first_seen_sha256,
        },
        verified_bundle=bundle,
        large_mode=large_mode,
        scratch_root=scratch_root,
    )


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def _hash_array_inputs(ids: Sequence[str], vectors: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(_canonical_json(list(ids)))
    digest.update(str(vectors.dtype).encode())
    digest.update(_canonical_json(list(vectors.shape)))
    digest.update(np.ascontiguousarray(vectors).tobytes())
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _string_ids(array: np.ndarray, name: str) -> list[str]:
    if array.ndim != 1 or array.dtype.kind not in {"U", "S"}:
        raise ValueError(f"{name} must be a one-dimensional string array; numeric IDs are forbidden")
    values = []
    for value in array.tolist():
        values.append(value.decode("utf-8") if isinstance(value, bytes) else value)
    return values


def _load_npz(path: Path, required: set[str]) -> dict[str, np.ndarray]:
    try:
        with np.load(path, allow_pickle=False) as data:
            if set(data.files) != required:
                raise ValueError(
                    f"{path} arrays mismatch; missing={sorted(required - set(data.files))}, "
                    f"extra={sorted(set(data.files) - required)}"
                )
            return {key: np.asarray(data[key]) for key in required}
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--candidate-config", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True,
                        help="NPZ with article_ids and article_vectors")
    parser.add_argument("--queries", type=Path, required=True,
                        help="NPZ with customer_ids and customer_vectors")
    parser.add_argument("--article-first-seen", type=Path, required=True,
                        help="JSON object mapping article_id to first observed date")
    parser.add_argument("--scoring-date", required=True)
    parser.add_argument("--day-index", type=int, required=True)
    parser.add_argument("--cohort-id", required=True)
    parser.add_argument("--spine-type", choices=("active_day", "replay_day"), required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--large-mode", action="store_true")
    parser.add_argument("--scratch-root", type=Path)
    return parser.parse_args(argv)


def main(argv=None) -> dict[str, Any]:
    args = parse_args(argv)
    bundle = load_inference_bundle(args.bundle)
    config = load_candidate_config(args.candidate_config)
    catalog = _load_npz(args.catalog, {"article_ids", "article_vectors"})
    queries = _load_npz(args.queries, {"customer_ids", "customer_vectors"})
    if bundle.complete and args.catalog.resolve() != bundle.artifact_path("catalog_arrays"):
        raise ValueError("--catalog must be the verified bundle catalog_arrays artifact")
    try:
        first_seen = json.loads(args.article_first_seen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read article first-seen map: {exc}") from exc
    if not isinstance(first_seen, dict):
        raise ValueError("article first-seen input must be a JSON object")
    result = build_daily_partition(
        bundle=bundle,
        config=config,
        article_ids=_string_ids(catalog["article_ids"], "article_ids"),
        article_vectors=catalog["article_vectors"],
        article_first_seen=first_seen,
        customer_ids=_string_ids(queries["customer_ids"], "customer_ids"),
        customer_vectors=queries["customer_vectors"],
        scoring_date=args.scoring_date,
        day_index=args.day_index,
        cohort_id=args.cohort_id,
        spine_type=args.spine_type,
        out_root=args.out_root,
        batch_size=args.batch_size,
        large_mode=args.large_mode,
        scratch_root=args.scratch_root,
        catalog_sha256=_file_sha256(args.catalog),
        query_sha256=_file_sha256(args.queries),
        first_seen_sha256=_file_sha256(args.article_first_seen),
    )
    print(json.dumps(result["manifest"], sort_keys=True))
    return result


if __name__ == "__main__":
    main()
