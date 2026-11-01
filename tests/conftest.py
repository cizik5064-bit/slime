from __future__ import annotations

import json
from pathlib import Path

import pytest

from slime.config import Config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(tmp_path / "slime-home")


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
