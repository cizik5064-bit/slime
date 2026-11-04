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
    """Server and proxy projects supported by Slime."""

    PAPER = "paper"
    FOLIA = "folia"
    PURPUR = "purpur"
    VELOCITY = "velocity"
    WATERFALL = "waterfall"

    @property
    def display_name(self) -> str:
        return {
            Project.PAPER: "Paper",
            Project.FOLIA: "Folia",
            Project.PURPUR: "Purpur",
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

#: Aikar's "performant" JVM flags, used as the default for new servers.
#: See https://mcflags.emc.gs/ for the reasoning behind every value.
AIKAR_FLAGS: tuple[str, ...] = (
    "-XX:+UseG1GC",
    "-XX:+ParallelRefProcEnabled",
    "-XX:MaxGCPauseMillis=200",
    "-XX:+UnlockExperimentalVMOptions",
    "-XX:+DisableExplicitGC",
    "-XX:+AlwaysPreTouch",
    "-XX:G1NewSizePercent=30",
    "-XX:G1MaxNewSizePercent=40",
    "-XX:G1HeapRegionSize=8M",
    "-XX:G1ReservePercent=20",
    "-XX:G1HeapWastePercent=5",
    "-XX:G1MixedGCCountTarget=4",
    "-XX:InitiatingHeapOccupancyPercent=15",
    "-XX:G1MixedGCLiveThresholdPercent=90",
    "-XX:G1RSetUpdatingPauseTimePercent=5",
    "-XX:SurvivorRatio=32",
    "-XX:+PerfDisableSharedMem",
    "-XX:MaxTenuringThreshold=1",
    "-Dusing.aikars.flags=https://mcflags.emc.gs",
    "-Daikars.new.flags=true",
)

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


def validate_cpu_cores(cores: int) -> int:
    if isinstance(cores, bool) or not isinstance(cores, int):
        raise ValidationError("CPU cores must be an integer.")
    if not 1 <= cores <= 1024:
        raise ValidationError("CPU cores must be between 1 and 1024.")
    return cores


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
    min_memory_mb: int | None = None
    cpu_cores: int | None = None
    port: int = 25565
    java_path: str | None = None
    eula_accepted: bool = False
    jar_file: str = "server.jar"
    extra_args: list[str] = field(default_factory=lambda: list(AIKAR_FLAGS))
    recovery_args: list[str] = field(default_factory=list)
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
        if self.min_memory_mb is not None:
            self.min_memory_mb = validate_memory(self.min_memory_mb)
            if self.min_memory_mb > self.memory_mb:
                raise ValidationError(
                    "Minimum memory (min_memory_mb) cannot exceed maximum memory "
                    "(memory_mb)."
                )
        if self.cpu_cores is not None:
            self.cpu_cores = validate_cpu_cores(self.cpu_cores)
        self.port = validate_port(self.port)
        if not self.jar_file or "/" in self.jar_file or "\\" in self.jar_file:
            raise ValidationError("Jar file must be a plain file name.")
        if not isinstance(self.extra_args, list):
            raise ValidationError("extra_args must be a list of strings.")
        self.extra_args = [str(arg) for arg in self.extra_args]
        if not isinstance(self.recovery_args, list):
            raise ValidationError("recovery_args must be a list of strings.")
        self.recovery_args = [str(arg) for arg in self.recovery_args]

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
            "min_memory_mb": self.min_memory_mb,
            "cpu_cores": self.cpu_cores,
            "port": self.port,
            "eula_accepted": self.eula_accepted,
            "jar_file": self.jar_file,
            "extra_args": list(self.extra_args),
            "recovery_args": list(self.recovery_args),
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

        def integer(field_name: str, default: int) -> int:
            value = data.get(field_name, default)
            if isinstance(value, bool):
                raise ValidationError(
                    f"Server '{name}' metadata field '{field_name}' must be an integer."
                )
            try:
                return int(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    f"Server '{name}' metadata field '{field_name}' must be an "
                    f"integer, got {value!r}."
                ) from exc

        def optional_integer(field_name: str) -> int | None:
            value = data.get(field_name)
            if value is None or value == "":
                return None
            if isinstance(value, bool):
                raise ValidationError(
                    f"Server '{name}' metadata field '{field_name}' must be an integer."
                )
            try:
                return int(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    f"Server '{name}' metadata field '{field_name}' must be an "
                    f"integer, got {value!r}."
                ) from exc

        extra_args = data.get("extra_args")
        if extra_args is None:
            extra_args = []
        elif not isinstance(extra_args, list):
            raise ValidationError(
                f"Server '{name}' metadata field 'extra_args' must be a list of strings."
            )

        recovery_args = data.get("recovery_args")
        if recovery_args is None:
            recovery_args = []
        elif not isinstance(recovery_args, list):
            raise ValidationError(
                f"Server '{name}' metadata field 'recovery_args' must be a list of strings."
            )

        java_path = data.get("java_path")
        if java_path is not None:
            java_path = str(java_path) or None

        created_at = data.get("created_at")
        if not created_at:
            created_at = datetime.now(UTC).isoformat(timespec="seconds")

        try:
            minecraft_version = str(data["minecraft_version"])
        except KeyError as exc:
            raise ValidationError(
                f"Server '{name}' metadata is missing the 'minecraft_version' field."
            ) from exc

        return cls(
            name=name,
            project=Project.parse(str(data.get("project", "paper"))),
            minecraft_version=minecraft_version,
            build=integer("build", 0),
            java_major=integer("java_major", 21),
            memory_mb=integer("memory_mb", 2048),
            min_memory_mb=optional_integer("min_memory_mb"),
            cpu_cores=optional_integer("cpu_cores"),
            port=integer("port", 25565),
            java_path=java_path,
            eula_accepted=bool(data.get("eula_accepted", False)),
            jar_file=str(data.get("jar_file", "server.jar")),
            extra_args=[str(arg) for arg in extra_args],
            recovery_args=[str(arg) for arg in recovery_args],
            created_at=str(created_at),
            schema=integer("schema", 1),
        )


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
