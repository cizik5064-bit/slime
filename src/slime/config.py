"""Configuration and on-disk layout.

Everything Slime owns lives in ``~/.slime`` by default::

    ~/.slime/
      config.toml
      servers/<name>/        # the working directory of each Minecraft server
      java/<runtime>/        # Temurin JDKs installed by Slime
      cache/                 # downloaded archives and temporary files
      logs/                  # Slime and server console logs
      backups/<name>/        # .7z backups created for each server

Set ``SLIME_HOME`` (or pass ``--home``) to use a different location.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from . import __version__
from .errors import ConfigError, ValidationError
from .models import validate_java_major, validate_memory, validate_port

APP_DIR_NAME = ".slime"
CONFIG_FILE_NAME = "config.toml"

#: Values that may be changed through ``slime config set``.
EDITABLE_SETTINGS = (
    "default_memory_mb",
    "default_java_major",
    "default_port",
    "accept_eula_default",
)


def default_home() -> Path:
    """Return the Slime home directory, honouring ``SLIME_HOME``."""
    env = os.environ.get("SLIME_HOME", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / APP_DIR_NAME


@dataclass(slots=True)
class Settings:
    """User-tunable settings stored in ``config.toml``."""

    default_memory_mb: int = 2048
    default_java_major: int = 21
    default_port: int = 25565
    accept_eula_default: bool = False
    fill_base_url: str = "https://fill.papermc.io/v3"
    purpur_base_url: str = "https://api.purpurmc.org/v2/purpur"
    adoptium_base_url: str = "https://api.adoptium.net/v3"
    modrinth_base_url: str = "https://api.modrinth.com/v2"
    hangar_base_url: str = "https://hangar.papermc.io/api/v1"
    user_agent: str = f"Slime/{__version__} (+https://github.com/cizik5064-bit/slime)"
    request_timeout: float = 30.0


@dataclass(slots=True)
class Paths:
    """All filesystem locations used by Slime."""

    home: Path
    servers: Path
    java: Path
    cache: Path
    logs: Path
    backups: Path
    config_file: Path

    @classmethod
    def under(cls, home: Path) -> Paths:
        home = home.expanduser()
        return cls(
            home=home,
            servers=home / "servers",
            java=home / "java",
            cache=home / "cache",
            logs=home / "logs",
            backups=home / "backups",
            config_file=home / CONFIG_FILE_NAME,
        )

    def ensure(self) -> None:
        for directory in (
            self.home,
            self.servers,
            self.java,
            self.cache,
            self.logs,
            self.backups,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _dump_settings(settings: Settings) -> str:
    general = (
        "default_memory_mb",
        "default_java_major",
        "default_port",
        "accept_eula_default",
    )
    network = (
        "fill_base_url",
        "purpur_base_url",
        "adoptium_base_url",
        "modrinth_base_url",
        "hangar_base_url",
        "user_agent",
        "request_timeout",
    )
    lines = [
        "# Slime configuration. See https://github.com/cizik5064-bit/slime",
        "",
        "[general]",
    ]
    lines += [f"{key} = {_toml_value(getattr(settings, key))}" for key in general]
    lines += ["", "[network]"]
    lines += [f"{key} = {_toml_value(getattr(settings, key))}" for key in network]
    return "\n".join(lines) + "\n"


def _coerce(key: str, value: Any) -> Any:
    """Coerce a TOML value to the type of the matching Settings field."""
    template = getattr(Settings(), key)
    if isinstance(template, bool):
        if not isinstance(value, bool):
            raise ConfigError(f"Setting '{key}' must be true or false.")
        return value
    if isinstance(template, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"Setting '{key}' must be an integer.")
        return value
    if isinstance(template, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"Setting '{key}' must be a number.")
        return float(value)
    if not isinstance(value, str):
        raise ConfigError(f"Setting '{key}' must be a string.")
    return value


class Config:
    """Loaded configuration plus the paths it applies to."""

    def __init__(self, home: Path | None = None) -> None:
        self.paths = Paths.under((home or default_home()).expanduser())
        try:
            self.paths.ensure()
        except OSError as exc:
            raise ConfigError(
                f"Cannot create Slime home at {self.paths.home}: {exc}",
                hint="Set SLIME_HOME to a writable directory, for example: "
                "set SLIME_HOME=%USERPROFILE%\\slime",
            ) from exc
        self.settings = self._load()
        if not self.paths.config_file.exists():
            self.save()

    # ------------------------------------------------------------------ load
    def _load(self) -> Settings:
        path = self.paths.config_file
        if not path.exists():
            return Settings()
        try:
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(
                f"Cannot read {path}: {exc}",
                hint="Fix or delete the file; Slime will recreate it with defaults.",
            ) from exc

        flat: dict[str, Any] = {}
        for section in data.values():
            if isinstance(section, dict):
                flat.update(section)

        known = {field.name for field in fields(Settings)}
        values: dict[str, Any] = {}
        for key, value in flat.items():
            if key in known:
                values[key] = _coerce(key, value)
        settings = Settings(**values)
        try:
            validate_memory(settings.default_memory_mb)
            validate_port(settings.default_port)
            validate_java_major(settings.default_java_major)
        except ValidationError as exc:
            raise ConfigError(
                f"Invalid setting in {path}: {exc.message}",
                hint="Fix the value or delete the file; Slime will recreate it with defaults.",
            ) from exc
        return settings

    # ------------------------------------------------------------------ save
    def save(self) -> None:
        path = self.paths.config_file
        tmp = path.with_name(path.name + ".tmp")
        try:
            tmp.write_text(_dump_settings(self.settings), encoding="utf-8", newline="\n")
            os.replace(tmp, path)
        except OSError as exc:
            raise ConfigError(f"Cannot write {path}: {exc}") from exc

    # ------------------------------------------------------------------- set
    def set(self, key: str, raw_value: str) -> Any:
        """Set one editable setting from a CLI string and persist it."""
        key = key.strip().lower()
        if key not in EDITABLE_SETTINGS:
            raise ConfigError(
                f"Unknown setting '{key}'.",
                hint="Editable settings: " + ", ".join(EDITABLE_SETTINGS),
            )

        current = getattr(self.settings, key)
        if isinstance(current, bool):
            normalized = raw_value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                value: Any = True
            elif normalized in {"0", "false", "no", "off"}:
                value = False
            else:
                raise ConfigError(f"'{key}' expects true or false.")
        elif isinstance(current, int):
            try:
                value = int(raw_value)
            except ValueError as exc:
                raise ConfigError(f"'{key}' expects an integer.") from exc
        else:
            value = raw_value

        if key == "default_memory_mb" and not 512 <= value <= 65536:
            raise ConfigError("default_memory_mb must be between 512 and 65536.")
        if key == "default_port" and not 1 <= value <= 65535:
            raise ConfigError("default_port must be between 1 and 65535.")
        if key == "default_java_major" and value not in {8, 11, 16, 17, 21, 25}:
            raise ConfigError("default_java_major must be one of: 8, 11, 16, 17, 21, 25.")

        setattr(self.settings, key, value)
        self.save()
        return value
