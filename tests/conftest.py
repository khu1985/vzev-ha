import os
import sys
from pathlib import Path

import pytest

HIER = Path(__file__).parent
sys.path.insert(0, str(HIER))
sys.path.insert(0, str(HIER.parent / "vzev" / "app"))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
os.environ.setdefault("VZEV_KEINE_SENSOREN", "1")  # kein Hintergrund-Thread in den Tests

import daten  # noqa: E402


@pytest.fixture(scope="session")
def ordner(tmp_path_factory):
    return daten.datenordner(tmp_path_factory.mktemp("vzev"))


@pytest.fixture(scope="session")
def ergebnis(ordner):
    import core
    return core.run(ordner / "primeo", ordner / "vzev.yaml")
