import pytest

from marketrank import splits


def test_ope_env_context_is_allowed_only_after_reserved_slice() -> None:
    splits.assert_slice_usage(
        "ope_env", usage="context_only", target_date="2020-09-09"
    )

    with pytest.raises(ValueError, match="after 2020-09-08"):
        splits.assert_slice_usage(
            "ope_env", usage="context_only", target_date="2020-09-08"
        )


@pytest.mark.parametrize(
    "usage",
    ["label", "fit", "tune", "calibration", "ope", "standalone_metric"],
)
def test_ope_env_rejects_outcome_and_model_uses(usage: str) -> None:
    with pytest.raises(ValueError, match="only usage='context_only'"):
        splits.assert_slice_usage("ope_env", usage=usage, target_date="2020-09-09")


def test_context_audit_is_complete_and_deterministic() -> None:
    audit = splits.ope_env_context_audit(
        consumer_job="build_candidates",
        target_dates=["2020-09-16", "2020-09-09", "2020-09-09"],
        row_count=123,
        input_snapshot="snapshot-abc",
    )

    assert audit == {
        "source_slice": "ope_env",
        "usage": "context_only",
        "consumer_job": "build_candidates",
        "target_dates": ["2020-09-09", "2020-09-16"],
        "row_count": 123,
        "input_snapshot": "snapshot-abc",
    }


def test_context_audit_rejects_missing_provenance() -> None:
    with pytest.raises(ValueError, match="consumer_job"):
        splits.ope_env_context_audit(
            consumer_job="",
            target_dates=["2020-09-09"],
            row_count=1,
            input_snapshot="snapshot-abc",
        )
