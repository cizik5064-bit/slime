from __future__ import annotations

import tomllib
from pathlib import Path

from slime import __version__
from slime.api.adoptium import AdoptiumClient
from slime.api.papermc import PaperMCClient
from slime.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_version_matches_package() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text("utf-8"))
    assert pyproject["project"]["version"] == __version__


def test_user_agents_include_version() -> None:
    assert __version__ in Settings().user_agent
    paper = PaperMCClient()
    adoptium = AdoptiumClient()
    try:
        assert paper.user_agent == f"Slime/{__version__}"
        assert adoptium.user_agent == f"Slime/{__version__}"
    finally:
        paper.close()
        adoptium.close()
