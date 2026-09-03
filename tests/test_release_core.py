from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import hmac
import json
from pathlib import Path

import pytest

from marketrank.release import (
    REQUIRED_SOURCES,
    ReleaseValidationError,
    build_release,
    dumps_release,
    opaque_customer_ref,
    reciprocal_rank_fusion,
    validate_customer_ref_key,
    validate_source_rows,
)


FIXTURES = Path(__file__).parent / "fixtures/release"
TEST_CUSTOMER_REF_KEY = b"test-only-marketrank-customer-ref-key-material"


def load_fixture() -> dict:
    return json.loads((FIXTURES / "valid-input.json").read_text())


def singleton_sources() -> dict[str, list[dict[str, object]]]:
    article_by_source = {
        "ann": "0000000001",
        "repurchase": "0000000001",
        "category_pop": "0000000002",
        "global_pop": "0000000002",
        "covisit": "0000000003",
    }
    return {
        source: [{
            "customer_id": "customer",
            "article_id": article_by_source[source],
            "source": source,
            "source_rank": 1,
        }]
        for source in REQUIRED_SOURCES
    }


def test_missing_source_is_a_hard_error() -> None:
    sources = json.loads((FIXTURES / "missing-source.json").read_text())
    with pytest.raises(ReleaseValidationError, match="missing=.*covisit"):
        validate_source_rows(sources)


@pytest.mark.parametrize("failure", ["wrong_tag", "duplicate_article", "duplicate_rank"])
def test_inconsistent_source_rows_are_hard_errors(failure: str) -> None:
    sources = singleton_sources()
    if failure == "wrong_tag":
        sources["ann"][0]["source"] = "covisit"
    elif failure == "duplicate_article":
        sources["ann"].append(dict(sources["ann"][0], source_rank=2))
    else:
        sources["ann"].append(dict(sources["ann"][0], article_id="0000000099"))
    with pytest.raises(ReleaseValidationError):
        validate_source_rows(sources)


def test_equal_weight_rrf_is_exact_and_ties_use_article_id() -> None:
    fused = reciprocal_rank_fusion(singleton_sources())["customer"]
    assert [item.article_id for item in fused] == [
        "0000000001", "0000000002", "0000000003"
    ]
    assert fused[0].score == fused[1].score == Fraction(2, 61)
    assert fused[2].score == Fraction(1, 61)


def test_rrf_uses_each_source_rank_in_the_exact_formula() -> None:
    sources = singleton_sources()
    sources["repurchase"][0]["source_rank"] = 2
    fused = reciprocal_rank_fusion(sources)["customer"]
    article = next(item for item in fused if item.article_id == "0000000001")
    assert article.score == Fraction(1, 60 + 1) + Fraction(1, 60 + 2)


def test_rrf_rejects_non_v1_k() -> None:
    with pytest.raises(ReleaseValidationError, match="requires k=60"):
        reciprocal_rank_fusion(singleton_sources(), k=10)


def test_opaque_references_are_deterministic_and_release_scoped() -> None:
    first = opaque_customer_ref(
        "release-a",
        "raw-customer",
        customer_ref_key=TEST_CUSTOMER_REF_KEY,
        allow_test_key=True,
    )
    expected = hmac.new(
        TEST_CUSTOMER_REF_KEY,
        b"marketrank-workbench-v1\0release-a\0raw-customer",
        hashlib.sha256,
    ).hexdigest()[:16]
    assert first == f"demo_{expected}"
    assert first == opaque_customer_ref(
        "release-a",
        "raw-customer",
        customer_ref_key=TEST_CUSTOMER_REF_KEY,
        allow_test_key=True,
    )
    assert first != opaque_customer_ref(
        "release-b",
        "raw-customer",
        customer_ref_key=TEST_CUSTOMER_REF_KEY,
        allow_test_key=True,
    )
    assert first != opaque_customer_ref(
        "release-a",
        "raw-customer",
        customer_ref_key=b"another-realistic-32-byte-key-value!!",
    )
    assert first.startswith("demo_") and "raw-customer" not in first


def test_customer_reference_key_rejects_short_and_test_only_material() -> None:
    with pytest.raises(ReleaseValidationError, match="at least 32 bytes"):
        validate_customer_ref_key(b"short")
    with pytest.raises(ReleaseValidationError, match="test-only"):
        validate_customer_ref_key(TEST_CUSTOMER_REF_KEY)
    assert validate_customer_ref_key(TEST_CUSTOMER_REF_KEY, allow_test_key=True) == TEST_CUSTOMER_REF_KEY


def build_synthetic_release() -> dict[str, object]:
    fixture = load_fixture()
    metadata = {
        f"{index:010d}": {
            "product_name": f"Product {index}",
            "product_type_name": "Top",
            "colour_group_name": "Blue",
            "department_name": "Demo",
            "index_group_name": "Ladieswear",
            "garment_group_name": "Jersey",
        }
        for index in range(1, 13)
    }
    counts = {source: len(fixture["sources"][source]) for source in REQUIRED_SOURCES}
    return build_release(
        release_id="synthetic-release-v1",
        candidate_sources=fixture["sources"],
        article_metadata=metadata,
        ceiling=fixture["ceiling"],
        source_row_counts=counts,
        demo_customer_ids=["raw-customer-a"],
        customer_ref_key=TEST_CUSTOMER_REF_KEY,
        allow_test_customer_ref_key=True,
    )


def test_release_is_top_12_unique_ordered_and_contains_no_raw_id() -> None:
    release = build_synthetic_release()
    customer = release["customers"][0]
    recommendations = customer["recommendations"]
    assert [item["position"] for item in recommendations] == list(range(1, 13))
    assert len({item["article_id"] for item in recommendations}) == 12
    assert "raw-customer-a" not in dumps_release(release)
    assert release["meta"]["ranking_mode"] == "baseline_fusion"
    assert release["meta"]["provenance_status"] == "backfilled"


def test_serialization_is_byte_identical() -> None:
    release = build_synthetic_release()
    assert dumps_release(release).encode() == dumps_release(deepcopy(release)).encode()


def test_ceiling_row_count_mismatch_is_rejected() -> None:
    fixture = load_fixture()
    counts = {source: len(fixture["sources"][source]) for source in REQUIRED_SOURCES}
    counts["ann"] += 1
    with pytest.raises(ReleaseValidationError, match="row count"):
        build_release(
            release_id="broken",
            candidate_sources=fixture["sources"],
            article_metadata={},
            ceiling=fixture["ceiling"],
            source_row_counts=counts,
            demo_customer_ids=["raw-customer-a"],
            customer_ref_key=TEST_CUSTOMER_REF_KEY,
            allow_test_customer_ref_key=True,
        )
