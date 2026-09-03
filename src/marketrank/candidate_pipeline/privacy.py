"""Identifier boundary for synthetic fixtures and opaque release references.

Accepted customer identifiers are either ``synthetic_...``/``synthetic-...``
test labels or release-safe opaque references shaped as ``v2c_`` followed by
24 lowercase hexadecimal characters. Kaggle's raw 64-hex customer IDs are
explicitly rejected.
"""

from __future__ import annotations

import re

SYNTHETIC_CUSTOMER_PATTERN = re.compile(r"^synthetic(?:[_-][A-Za-z0-9]+)+$")
OPAQUE_CUSTOMER_PATTERN = re.compile(r"^v2c_[0-9a-f]{24}$")
RAW_CUSTOMER_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class CustomerIdentifierError(ValueError):
    """A customer identifier is neither documented synthetic nor opaque."""


def validate_customer_identifier(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise CustomerIdentifierError("customer identifier must be a non-empty string")
    if RAW_CUSTOMER_PATTERN.fullmatch(value):
        raise CustomerIdentifierError("raw 64-hex customer IDs are forbidden")
    if not (SYNTHETIC_CUSTOMER_PATTERN.fullmatch(value) or OPAQUE_CUSTOMER_PATTERN.fullmatch(value)):
        raise CustomerIdentifierError(
            "customer identifier must use the documented synthetic or opaque pattern"
        )
    return value
