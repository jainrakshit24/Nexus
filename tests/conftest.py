import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus.store import Store  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    # Keep global-tier records inside the tmp dir so tests never touch ~/.nexus
    import nexus.store as store_mod
    monkeypatch.setattr(store_mod, "GLOBAL_DIR", tmp_path / "global")
    return Store.init(tmp_path / "repo")
