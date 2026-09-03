from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).parent / "fixtures" / "contracts_v2"
SOURCES = {"repurchase", "category_pop", "global_pop", "covisit", "ann"}


def _load(name: str) -> dict:
    return json.loads((ROOT / name).read_text())


def test_frozen_contract_hashes_match() -> None:
    expected = {}
    for line in (ROOT / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        expected[name] = digest

    assert expected
    for name, digest in expected.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest


def test_candidate_configuration_freezes_five_sources_and_exact_search() -> None:
    config = _load("candidate-config.json")

    assert set(config["sources"]) == SOURCES
    assert config["sources"]["ann"]["algorithm"] == "exact_batched_inner_product"
    assert config["sources"]["ann"]["dtype"] == "float32"
    assert config["sources"]["covisit"]["recent_k"] == 10
    assert config["rrf_comparator"]["k"] == 60
    assert set(config["rrf_comparator"]["weights"]) == SOURCES


def test_primary_bundle_excludes_mutable_customer_snapshot_fields() -> None:
    bundle = _load("inference-bundle.json")
    allowed = set(bundle["allowed_customer_inputs"])
    forbidden = set(bundle["forbidden_customer_inputs"])

    assert not allowed & forbidden
    assert {"age_bucket", "club_member_status", "fashion_news_frequency"} <= forbidden
    assert bundle["artifact_available_after"] == "2020-07-14"


def test_candidate_fixture_has_both_spines_and_enforces_article_eligibility() -> None:
    fixture = _load("candidate-set.json")
    first_seen = {
        row["article_id"]: date.fromisoformat(row["first_observed_transaction_date"])
        for row in fixture["articles"]
    }
    spines = set()
    has_unreachable_positive = False

    for manifest in fixture["date_manifests"]:
        assert set(manifest["source_artifacts"]) == SOURCES
    for group in fixture["groups"]:
        scoring_date = date.fromisoformat(group["scoring_date"])
        spines.add(group["spine_type"])
        candidate_ids = {row["article_id"] for row in group["candidates"]}
        for article_id in candidate_ids:
            assert first_seen[article_id] < scoring_date
        if set(group["truth_articles"]) - candidate_ids:
            has_unreachable_positive = True

    assert spines == {"active_day", "replay_day"}
    assert has_unreachable_positive


def test_api_fixture_is_ordering_only_and_contains_no_forbidden_claim_fields() -> None:
    payload = _load("api-recommendations.json")
    encoded = json.dumps(payload).lower()

    assert payload["ranking_mode"] == "trained_ranker"
    assert payload["score_semantics"] == "ordering_only"
    assert "ordering_score" in encoded
    assert '"probability"' not in encoded
    assert '"confidence"' not in encoded
    assert '"customer_id"' not in encoded
    assert '"price"' not in encoded
    assert '"inventory"' not in encoded
