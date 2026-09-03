#!/usr/bin/env python3
"""Build the compact, deterministic historical workbench release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from marketrank.release.artifacts import (
    find_default_articles,
    load_article_metadata,
    load_sample_rows,
    select_demo_customers,
    read_customer_ref_key,
    validate_physical_snapshot,
)
from marketrank.release.core import build_release, dumps_release, reciprocal_rank_fusion


DEFAULT_RELEASE_ID = "historical-demo-2020-08-12-v1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=Path("artifacts/candidates/sources"))
    parser.add_argument("--ceiling", type=Path, default=Path("artifacts/candidates/ceiling.json"))
    parser.add_argument("--articles", type=Path, default=None)
    parser.add_argument("--release-id", default=DEFAULT_RELEASE_ID)
    parser.add_argument(
        "--customer-ref-key-file",
        type=Path,
        required=True,
        help="external file containing at least 32 bytes of non-test key material",
    )
    parser.add_argument("--demo-customers", type=int, default=8)
    parser.add_argument("--output", type=Path, default=Path("workbench/public/data/demo-release.json"))
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    candidates = args.candidates if args.candidates.is_absolute() else repo_root / args.candidates
    ceiling = args.ceiling if args.ceiling.is_absolute() else repo_root / args.ceiling
    output = args.output if args.output.is_absolute() else repo_root / args.output
    articles = args.articles or find_default_articles(repo_root)
    articles = articles if articles.is_absolute() else repo_root / articles
    customer_ref_key = read_customer_ref_key(args.customer_ref_key_file)

    snapshot = validate_physical_snapshot(candidates, ceiling)
    customer_ids = select_demo_customers(snapshot, args.release_id, args.demo_customers)
    sources = load_sample_rows(snapshot, customer_ids)
    fused = reciprocal_rank_fusion(sources)
    article_ids = {
        candidate.article_id
        for customer_id in customer_ids
        for candidate in fused[customer_id]
    }
    metadata = load_article_metadata(articles, article_ids)
    release = build_release(
        release_id=args.release_id,
        candidate_sources=sources,
        article_metadata=metadata,
        ceiling=snapshot.ceiling,
        source_row_counts=snapshot.source_row_counts,
        demo_customer_ids=customer_ids,
        customer_ref_key=customer_ref_key,
    )
    schema = json.loads(
        (repo_root / "contracts/workbench-release.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(release)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(dumps_release(release), encoding="utf-8")
    print(f"wrote {len(customer_ids)} demo customers to {output}")


if __name__ == "__main__":
    main()
