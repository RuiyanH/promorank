import os
import tempfile
from pathlib import Path

import pytest

# Tests own their catalog and spill directory. In particular they must never
# write to (or depend on a mount for) the developer's real Iceberg warehouse.
_test_runtime = tempfile.TemporaryDirectory(prefix="marketrank-pytest-")
_test_root = Path(_test_runtime.name)
os.environ["MARKETRANK_WAREHOUSE"] = str(_test_root / "warehouse")
os.environ["MARKETRANK_SPARK_TMP"] = str(_test_root / "spill")
os.environ["SPARK_CONF_DIR"] = str(_test_root / "conf")

# Importing marketrank.config is what sets SPARK_CONF_DIR and renders
# conf/spark-defaults.conf, which is where the Iceberg catalog is defined. It
# has to happen before any session is built -- import order is the mechanism.
from marketrank import config  # noqa: F401
from marketrank.spark import get_spark


@pytest.fixture(scope="session")
def spark():
    """
    One local Spark session for the whole suite.

    Session-scoped because JVM startup dominates: two to three minutes of the
    CI job is this fixture, and paying it per test would make the Spark tests
    too expensive to leave switched on -- which is how gate 1 quietly stops
    being enforced by the machine.
    """
    s = get_spark(app_name="pytest", driver_memory="2g", master="local[2]")
    yield s
    s.stop()
