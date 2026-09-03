import importlib.util
from pathlib import Path

import pytest

from marketrank.release import ReleaseValidationError
from marketrank.release.artifacts import read_customer_ref_key
from test_release_core import TEST_CUSTOMER_REF_KEY


_SCRIPT = Path(__file__).parents[1] / "scripts/build_workbench_fixture.py"
_SPEC = importlib.util.spec_from_file_location("build_workbench_fixture", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
parse_args = _MODULE.parse_args


def test_physical_cli_requires_external_key_file() -> None:
    with pytest.raises(SystemExit) as exc:
        parse_args([])
    assert exc.value.code == 2


@pytest.mark.parametrize("key", [b"short", TEST_CUSTOMER_REF_KEY])
def test_physical_key_reader_rejects_short_or_test_only_key(tmp_path: Path, key: bytes) -> None:
    path = tmp_path / "private-key"
    path.write_bytes(key)
    with pytest.raises(ReleaseValidationError):
        read_customer_ref_key(path)
