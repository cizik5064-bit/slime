from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from slime.config import Config, Settings, default_home
from slime.errors import ConfigError


def test_config_creates_home_and_default_file(tmp_path: Path) -> None:
    home = tmp_path / "home"
    config = Config(home)
    assert config.paths.home == home
    assert config.paths.servers.is_dir()
    assert config.paths.java.is_dir()
    assert config.paths.cache.is_dir()
    assert config.paths.logs.is_dir()
    assert config.paths.config_file.is_file()
    assert config.settings == Settings()


def test_settings_round_trip(tmp_path: Path) -> None:
    home = tmp_path / "home"
    config = Config(home)
    config.settings.default_memory_mb = 4096
    config.settings.default_port = 25566
    config.settings.accept_eula_default = True
    config.save()

    reloaded = Config(home)
    assert reloaded.settings.default_memory_mb == 4096
    assert reloaded.settings.default_port == 25566
    assert reloaded.settings.accept_eula_default is True


def test_config_file_is_valid_toml(tmp_path: Path) -> None:
    config = Config(tmp_path / "home")
    data = tomllib.loads(config.paths.config_file.read_text(encoding="utf-8"))
    assert data["general"]["default_memory_mb"] == 2048
    assert "network" in data


def test_set_coerces_and_persists(tmp_path: Path) -> None:
    home = tmp_path / "home"
    config = Config(home)
    assert config.set("default_memory_mb", "4096") == 4096
    assert config.set("accept_eula_default", "yes") is True
    assert config.set("default_java_major", "17") == 17
    assert Config(home).settings.default_memory_mb == 4096


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("unknown", "1", "Unknown setting"),
        ("default_memory_mb", "abc", "expects an integer"),
        ("default_memory_mb", "128", "between 512"),
        ("default_port", "70000", "between 1"),
        ("default_java_major", "19", "must be one of"),
        ("accept_eula_default", "maybe", "true or false"),
    ],
)
def test_set_rejects_invalid_values(
    tmp_path: Path, key: str, value: str, match: str
) -> None:
    config = Config(tmp_path / "home")
    with pytest.raises(ConfigError, match=match):
        config.set(key, value)


def test_corrupt_toml_reports_error(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text("not = [valid", encoding="utf-8")
    with pytest.raises(ConfigError, match="Cannot read"):
        Config(home)


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("[general]\ndefault_port = 0\n", "Port must be between"),
        ("[general]\ndefault_memory_mb = 1\n", "Memory must be between"),
        ("[general]\ndefault_java_major = 19\n", "Unsupported Java major"),
    ],
)
def test_config_file_values_are_validated(
    tmp_path: Path, body: str, match: str
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError, match=match):
        Config(home)


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text(
        "[general]\ndefault_port = 25570\nfuture_key = \"x\"\n",
        encoding="utf-8",
    )
    config = Config(home)
    assert config.settings.default_port == 25570


def test_default_home_honours_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLIME_HOME", str(tmp_path / "custom"))
    assert default_home() == tmp_path / "custom"


def test_default_home_uses_user_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SLIME_HOME", raising=False)
    assert default_home().name == ".slime"
