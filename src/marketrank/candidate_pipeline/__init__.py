"""V2 candidate configuration, validation, and deterministic union helpers."""

from .config import CandidateConfig, load_candidate_config
from .guards import assert_large_output_path
from .privacy import validate_customer_identifier
from .spines import build_active_day_spine, build_replay_day_spine
from .union import (
    REQUIRED_SOURCES,
    daily_ann_to_candidate_source,
    union_candidate_sources,
    validate_spine_type,
)

__all__ = [
    "CandidateConfig",
    "REQUIRED_SOURCES",
    "assert_large_output_path",
    "build_active_day_spine",
    "build_replay_day_spine",
    "daily_ann_to_candidate_source",
    "load_candidate_config",
    "union_candidate_sources",
    "validate_customer_identifier",
    "validate_spine_type",
]
