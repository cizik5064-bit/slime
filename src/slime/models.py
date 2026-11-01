"""Core data models and validation rules.

This module intentionally depends only on the standard library so it can be
unit-tested and imported very cheaply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .errors import ValidationError

# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


class Project(StrEnum):
    """Projects published through the PaperMC Fill API."""

    PAPER = "paper"
    FOLIA = "folia"
    VELOCITY = "velocity"
    WATERFALL = "waterfall"

    @property
    def display_name(self) -> str:
        return {
            Project.PAPER: "Paper",
            Project.FOLIA: "Folia",
            Project.VELOCITY: "Velocity",
            Project.WATERFALL: "Waterfall",
        }[self]

    @property
    def is_proxy(self) -> bool:
        return self in (Project.VELOCITY, Project.WATERFALL)

    @property
    def kind(self) -> str:
        return "proxy" if self.is_proxy else "server"

    @classmethod
    def parse(cls, value: str | Project) -> Project:
        if isinstance(value, Project):
            return value
        normalized = str(value).strip().lower()
        try:
            return cls(normalized)
        except ValueError as exc:
            choices = ", ".join(project.value for project in Project)
            raise ValidationError(
                f"Unknown project '{value}'. Supported projects: {choices}."
            ) from exc


PROJECTS: tuple[Project, ...] = tuple(Project)

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def validate_server_name(name: str) -> str:
    """Validate a server name that is also used as a directory name."""
    name = name.strip()
    if not name:
        raise ValidationError("Server name cannot be empty.")
    if not _NAME_RE.match(name):
        raise ValidationError(
            "Invalid server name. Use 1-32 characters: letters, digits, '-' or '_', "
            "starting with a letter or digit.",
            hint="Example: my-server",
        )
    if name.upper() in _WINDOWS_RESERVED:
        raise ValidationError(f"'{name}' is a reserved name on Windows.")
    return name


def validate_port(port: int) -> int:
    if isinstance(port, bool) or not isinstance(port, int):
        raise ValidationError("Port must be an integer.")
    if not 1 <= port <= 65535:
        raise ValidationError("Port must be between 1 and 65535.")
    return port


def validate_memory(memory_mb: int) -> int:
    if isinstance(memory_mb, bool) or not isinstance(memory_mb, int):
        raise ValidationError("Memory must be an integer number of megabytes.")
    if not 512 <= memory_mb <= 65536:
        raise ValidationError("Memory must be between 512 and 65536 MB.")
    return memory_mb


def validate_java_major(major: int) -> int:
    if isinstance(major, bool) or not isinstance(major, int):
        raise ValidationError("Java major version must be an integer.")
    if major not in {8, 11, 16, 17, 21, 25}:
        raise ValidationError(
            f"Unsupported Java major version: {major}.",
            hint="Supported majors: 8, 11, 16, 17, 21, 25.",
        )
    return major


# ---------------------------------------------------------------------------
# Minecraft / Java version helpers
# ---------------------------------------------------------------------------

_RELEASE_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?(?:[-_]([0-9A-Za-z.\-]+))?$")
_SNAPSHOT_RE = re.compile(r"^(\d{2})w(\d{2})([a-z])$")


def version_key(version: str) -> tuple[int, int, int, int, int, str]:
    """Sortable key for Minecraft versions.

    Releases sort above snapshots and pre-releases of the same number. The
    function never raises: unknown formats sort last but deterministically.
    """
    text = version.strip()
    match = _RELEASE_RE.match(text)
    if match:
        major, minor, patch = (int(part or 0) for part in match.groups()[:3])
        pre = match.group(4)
        return (2, major, minor, patch, 0 if pre else 1, pre or "")
    snapshot = _SNAPSHOT_RE.match(text)
    if snapshot:
        year, week, letter = snapshot.groups()
        return (1, int(year), int(week), ord(letter) - ord("a"), 0, "")
    return (0, 0, 0, 0, 0, text)


def sort_versions(versions: list[str], *, reverse: bool = True) -> list[str]:
    """Return versions sorted newest-first by default."""
    return sorted(versions, key=version_key, reverse=reverse)


def required_java_major(project: Project | str, minecraft_version: str) -> int:
    """Return the Java major version a project/version combination needs."""
    project = Project.parse(project)
    if project is Project.VELOCITY:
        return 17
    if project is Project.WATERFALL:
        return 11

    text = minecraft_version.strip().lower()
    match = _RELEASE_RE.match(text)
    if not match:
        # Snapshots and unknown future formats target the modern runtime.
        return 21

    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    # Minecraft moved to calendar versioning in 2026 (26.1, 26.2, ...).
    # Fill reports Java 25 as the minimum for these releases.
    if major >= 26:
        return 25
    if (major, minor, patch) >= (1, 20, 5):
        return 21
    if (major, minor, patch) >= (1, 17, 0):
        return 17
    return 8


# ---------------------------------------------------------------------------
# API payloads
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DownloadInfo:
    """A single downloadable file attached to a PaperMC build."""

    name: str
    url: str
    sha256: str | None = None
    size: int | None = None


@dataclass(slots=True)
class BuildInfo:
    """A PaperMC build returned by the Fill API."""

    project: str
    version: str
    build: int
    channel: str = "STABLE"
    time: str | None = None
    downloads: dict[str, DownloadInfo] = field(default_factory=dict)

    @property
    def server_download(self) -> DownloadInfo:
        """Pick the runnable server jar from the downloads map."""
        preferred = ("server:default", "server", "application")
        for key in preferred:
            if key in self.downloads:
                return self.downloads[key]
        for key, download in self.downloads.items():
            if "server" in key.lower():
                return download
        if self.downloads:
            return next(iter(self.downloads.values()))
        raise ValidationError(
            f"Build {self.project} {self.version} #{self.build} has no downloadable files."
        )


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Server:
    """A server managed by Slime, persisted as ``servers/<name>/slime.json``."""

    name: str
    project: Project
    minecraft_version: str
    build: int
    java_major: int
    memory_mb: int = 2048
    port: int = 25565
    java_path: str | None = None
    eula_accepted: bool = False
    jar_file: str = "server.jar"
    extra_args: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    schema: int = 1

    def __post_init__(self) -> None:
        self.name = validate_server_name(self.name)
        self.project = Project.parse(self.project)
        self.minecraft_version = self.minecraft_version.strip()
        if not self.minecraft_version:
            raise ValidationError("Minecraft version cannot be empty.")
        if isinstance(self.build, bool) or not isinstance(self.build, int) or self.build < 0:
            raise ValidationError("Build number must be a non-negative integer.")
        self.java_major = validate_java_major(self.java_major)
        self.memory_mb = validate_memory(self.memory_mb)
        self.port = validate_port(self.port)
        if not self.jar_file or "/" in self.jar_file or "\\" in self.jar_file:
            raise ValidationError("Jar file must be a plain file name.")
        if not isinstance(self.extra_args, list):
            raise ValidationError("extra_args must be a list of strings.")
        self.extra_args = [str(arg) for arg in self.extra_args]

    @property
    def is_proxy(self) -> bool:
        return self.project.is_proxy

    @property
    def kind(self) -> str:
        return self.project.kind

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "name": self.name,
            "project": self.project.value,
            "minecraft_version": self.minecraft_version,
            "build": self.build,
            "java_major": self.java_major,
            "java_path": self.java_path,
            "memory_mb": self.memory_mb,
            "port": self.port,
            "eula_accepted": self.eula_accepted,
            "jar_file": self.jar_file,
            "extra_args": list(self.extra_args),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Server:
        if not isinstance(data, dict):
            raise ValidationError("Server metadata must be a JSON object.")
        try:
            name = str(data["name"])
        except KeyError as exc:
            raise ValidationError("Server metadata is missing the 'name' field.") from exc
        try:
            return cls(
                name=name,
                project=Project.parse(str(data.get("project", "paper"))),
                minecraft_version=str(data["minecraft_version"]),
                build=int(data.get("build", 0)),
                java_major=int(data.get("java_major", 21)),
                memory_mb=int(data.get("memory_mb", 2048)),
                port=int(data.get("port", 25565)),
                java_path=data.get("java_path"),
                eula_accepted=bool(data.get("eula_accepted", False)),
                jar_file=str(data.get("jar_file", "server.jar")),
                extra_args=list(data.get("extra_args") or []),
                created_at=str(data.get("created_at") or ""),
                schema=int(data.get("schema", 1)),
            )
        except KeyError as exc:
            raise ValidationError(
                f"Server '{name}' metadata is missing the {exc.args[0]!r} field."
            ) from exc


@dataclass(slots=True)
class JavaInstall:
    """A Java runtime Slime knows about."""

    major: int
    version: str
    path: str
    home: str
    source: str = "temurin"
    os: str = ""
    arch: str = ""
    installed_at: str = ""

    @property
    def executable(self) -> str:
        return self.path

    def to_dict(self) -> dict[str, Any]:
        return {
            "major": self.major,
            "version": self.version,
            "path": self.path,
            "home": self.home,
            "source": self.source,
            "os": self.os,
            "arch": self.arch,
            "installed_at": self.installed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JavaInstall:
        return cls(
            major=int(data["major"]),
            version=str(data.get("version", "")),
            path=str(data["path"]),
            home=str(data.get("home", "")),
            source=str(data.get("source", "temurin")),
            os=str(data.get("os", "")),
            arch=str(data.get("arch", "")),
            installed_at=str(data.get("installed_at", "")),
        )
