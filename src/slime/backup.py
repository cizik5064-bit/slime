"""Server backups stored as maximally compressed 7z archives.

A backup contains the server worlds, ``config/``, the ``plugins/`` and/or
``mods/`` folders the server's loader supports, root-level configuration files,
and ``logs/latest.log``. The server jar and Slime's own metadata files are
intentionally excluded. Archives are written with LZMA2 preset 9 plus the
"extreme" flag, the slowest and smallest 7z mode available.
"""

from __future__ import annotations

import builtins
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import py7zr

from .config import Config
from .errors import BackupError
from .models import Server, validate_server_name
from .store import ServerStore

MANIFEST_NAME = "slime-backup.json"
FORMAT_VERSION = 1
#: LZMA2 preset 9 with the extreme flag: maximum compression, lowest speed.
COMPRESSION_FILTERS: list[dict[str, int]] = [
    {"id": py7zr.FILTER_LZMA2, "preset": 9 | py7zr.PRESET_EXTREME}
]
_ARCHIVE_SUFFIX = ".7z"
_SIDECAR_SUFFIX = ".json"
#: Directories copied in full in addition to the world folders. ``plugins``
#: and ``mods`` are added per project capability; ``config`` is always included.
_CONTENT_DIRECTORIES = ("config",)
#: Root-level files that should never go into a backup.
_EXCLUDED_ROOT_NAMES = {"slime.json", "slime.pid"}
_EXCLUDED_ROOT_SUFFIXES = (
    ".jar",
    ".7z",
    ".zip",
    ".tar.gz",
    ".tgz",
    ".rar",
)

ProgressCallback = Callable[[str, int, int], None]


def _size_label(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            if unit == "B":
                return f"{size:.0f} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size_bytes} B"  # pragma: no cover - unreachable


def _timestamp_from_identifier(identifier: str) -> str:
    match = re.match(r"^(\d{8}-\d{6})", identifier)
    if match:
        try:
            value = datetime.strptime(match.group(1), "%Y%m%d-%H%M%S")
            return value.replace(tzinfo=UTC).isoformat(timespec="seconds")
        except ValueError:
            pass
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(slots=True)
class BackupInfo:
    """Metadata for one ``.7z`` backup archive."""

    identifier: str
    path: Path
    created_at: str
    size_bytes: int
    server: str
    project: str = ""
    minecraft_version: str = ""
    build: int = 0
    note: str = ""
    files: int = 0

    @property
    def size_label(self) -> str:
        return _size_label(self.size_bytes)

    @property
    def created_label(self) -> str:
        try:
            value = datetime.fromisoformat(self.created_at)
        except ValueError:
            return self.created_at
        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "path": str(self.path),
            "created_at": self.created_at,
            "size_bytes": self.size_bytes,
            "size": self.size_label,
            "server": self.server,
            "project": self.project,
            "minecraft_version": self.minecraft_version,
            "build": self.build,
            "note": self.note,
            "files": self.files,
        }


class BackupManager:
    """Create, list, restore and delete per-server backup archives."""

    def __init__(self, config: Config, store: ServerStore) -> None:
        self.config = config
        self.store = store
        self.root = config.paths.backups

    # ------------------------------------------------------------------ paths
    def directory(self, name: str) -> Path:
        return self.root / validate_server_name(name)

    def is_running(self, name: str) -> bool:
        return self.store.is_running(name)[0]

    # ---------------------------------------------------------------- create
    def create(
        self,
        server: Server,
        *,
        note: str = "",
        progress: ProgressCallback | None = None,
    ) -> BackupInfo:
        """Create a new backup archive for a stopped server."""
        if self.is_running(server.name):
            raise BackupError(
                f"Cannot create a backup while '{server.name}' is running.",
                hint="Stop the server first so the world files are consistent.",
            )
        server_dir = self.store.path(server.name)
        if not server_dir.is_dir():
            raise BackupError(
                f"Server directory is missing: {server_dir}",
                hint="Recreate the server or fix its metadata.",
            )
        files = self._collect(server, server_dir)
        if not files:
            raise BackupError(
                f"Nothing to back up in {server_dir}.",
                hint="Start the server at least once so it creates a world.",
            )

        destination = self.directory(server.name)
        destination.mkdir(parents=True, exist_ok=True)
        identifier = self._new_identifier(destination)
        archive = destination / f"{identifier}{_ARCHIVE_SUFFIX}"
        temporary = destination / f".{identifier}{_ARCHIVE_SUFFIX}.part"
        created_at = datetime.now(UTC).isoformat(timespec="seconds")
        manifest = {
            "format": FORMAT_VERSION,
            "created_at": created_at,
            "server": server.name,
            "project": server.project.value,
            "minecraft_version": server.minecraft_version,
            "build": server.build,
            "note": note,
            "files": len(files),
        }

        try:
            with py7zr.SevenZipFile(
                temporary, "w", filters=COMPRESSION_FILTERS
            ) as bundle:
                total = len(files)
                for index, (arcname, path) in enumerate(files, start=1):
                    bundle.write(path, arcname=arcname)
                    if progress is not None:
                        progress(arcname, index, total)
                bundle.writestr(
                    json.dumps(manifest, indent=2) + "\n", MANIFEST_NAME
                )
            os.replace(temporary, archive)
            self._write_sidecar(archive, manifest)
        except (OSError, ValueError, py7zr.exceptions.ArchiveError) as exc:
            temporary.unlink(missing_ok=True)
            raise BackupError(
                f"Could not create backup for '{server.name}': {exc}",
                hint="Check free disk space and permissions.",
            ) from exc

        return BackupInfo(
            identifier=identifier,
            path=archive,
            created_at=created_at,
            size_bytes=archive.stat().st_size,
            server=server.name,
            project=server.project.value,
            minecraft_version=server.minecraft_version,
            build=server.build,
            note=note,
            files=len(files),
        )

    # ------------------------------------------------------------------- list
    def list(self, server_name: str) -> list[BackupInfo]:
        """Return backups for one server, newest first."""
        directory = self.directory(server_name)
        if not directory.is_dir():
            return []
        backups = [
            self._info(server_name, archive)
            for archive in directory.glob(f"*{_ARCHIVE_SUFFIX}")
            if archive.is_file()
        ]
        backups.sort(key=lambda info: (info.created_at, info.identifier), reverse=True)
        return backups

    def list_all(self) -> builtins.list[BackupInfo]:
        """Return backups of every server, newest first."""
        backups: builtins.list[BackupInfo] = []
        for server in self.store.list():
            backups.extend(self.list(server.name))
        backups.sort(key=lambda info: (info.created_at, info.identifier), reverse=True)
        return backups

    def resolve(self, server_name: str, identifier: str) -> BackupInfo:
        """Find a backup by full name or an unambiguous prefix."""
        wanted = identifier.strip()
        if not wanted:
            raise BackupError("A backup id is required.")
        backups = self.list(server_name)
        for info in backups:
            if wanted in {info.identifier, info.path.name}:
                return info
        matches = [
            info
            for info in backups
            if info.identifier.startswith(wanted) or info.path.name.startswith(wanted)
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise BackupError(
                f"Backup '{wanted}' was not found for '{server_name}'.",
                hint="Run `slime backup list {name}` to see available backups.",
            )
        raise BackupError(
            f"Backup id '{wanted}' is ambiguous.",
            hint="Use the full backup id from `slime backup list`.",
        )

    # ----------------------------------------------------------------- delete
    def delete(self, server_name: str, identifier: str) -> BackupInfo:
        """Delete one backup archive and its metadata sidecar."""
        info = self.resolve(server_name, identifier)
        try:
            info.path.unlink()
            info.path.with_suffix(_SIDECAR_SUFFIX).unlink(missing_ok=True)
        except OSError as exc:
            raise BackupError(
                f"Could not delete backup {info.identifier}: {exc}",
                hint="Check permissions on the backups directory.",
            ) from exc
        return info

    # ---------------------------------------------------------------- restore
    def restore(self, server: Server, identifier: str) -> int:
        """Restore a backup into the server directory and return file count.

        World folders, ``config/`` and the content folders present in the
        archive are replaced as a whole so stale files from the current state
        cannot survive. Other root-level configuration files and
        ``logs/latest.log`` are overwritten individually. The server jar and
        Slime metadata are left untouched.
        """
        if self.is_running(server.name):
            raise BackupError(
                f"Cannot restore a backup while '{server.name}' is running.",
                hint="Stop the server first.",
            )
        info = self.resolve(server.name, identifier)
        server_dir = self.store.path(server.name)
        if not server_dir.is_dir():
            raise BackupError(f"Server directory is missing: {server_dir}")

        try:
            temporary = Path(
                tempfile.mkdtemp(
                    prefix=f"slime-restore-{server.name}-",
                    dir=self.config.paths.cache,
                )
            )
        except OSError as exc:
            raise BackupError(
                f"Could not prepare a restore directory: {exc}",
                hint="Check free disk space and permissions in the cache directory.",
            ) from exc
        try:
            try:
                with py7zr.SevenZipFile(info.path, "r") as bundle:
                    names = bundle.getnames()
                    self._validate_members(names)
                    bundle.extractall(path=str(temporary))
            except (OSError, py7zr.exceptions.ArchiveError) as exc:
                raise BackupError(
                    f"Could not read backup {info.identifier}: {exc}",
                    hint="The archive may be corrupt. Try another backup.",
                ) from exc

            try:
                restored = 0
                for entry in sorted(temporary.iterdir()):
                    if entry.name == MANIFEST_NAME:
                        continue
                    if entry.name == "logs":
                        restored += self._restore_latest_log(entry, server_dir)
                        continue
                    target = server_dir / entry.name
                    if entry.is_dir():
                        restored += self._replace_directory(entry, target)
                    else:
                        restored += self._replace_file(entry, target)
                return restored
            except OSError as exc:
                raise BackupError(
                    f"Could not restore backup {info.identifier}: {exc}",
                    hint="Check permissions and free disk space in the server directory.",
                ) from exc
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    # ---------------------------------------------------------------- helpers
    def _collect(
        self, server: Server, server_dir: Path
    ) -> builtins.list[tuple[str, Path]]:
        collected: dict[str, Path] = {}

        def add(path: Path) -> None:
            try:
                arcname = path.relative_to(server_dir).as_posix()
            except ValueError:
                return
            collected.setdefault(arcname, path)

        for world in self.store.world_directories(server.name):
            for path in self._walk_files(world):
                add(path)

        content_directories = (
            *_CONTENT_DIRECTORIES,
            *server.project.content_directories,
        )
        for directory_name in content_directories:
            directory = server_dir / directory_name
            if directory.is_dir():
                for path in self._walk_files(directory):
                    add(path)

        for entry in server_dir.iterdir():
            if entry.is_file() and self._include_root_file(entry):
                add(entry)

        latest_log = server_dir / "logs" / "latest.log"
        if latest_log.is_file():
            add(latest_log)

        return sorted(collected.items())

    @staticmethod
    def _walk_files(directory: Path) -> Iterator[Path]:
        for root, _dirs, files in os.walk(directory, followlinks=False):
            for filename in files:
                path = Path(root) / filename
                if path.is_file():
                    yield path

    @staticmethod
    def _include_root_file(path: Path) -> bool:
        if path.name in _EXCLUDED_ROOT_NAMES:
            return False
        return not path.name.lower().endswith(_EXCLUDED_ROOT_SUFFIXES)

    @staticmethod
    def _new_identifier(directory: Path) -> str:
        base = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        identifier = base
        counter = 2
        while (directory / f"{identifier}{_ARCHIVE_SUFFIX}").exists():
            identifier = f"{base}-{counter}"
            counter += 1
        return identifier

    def _info(self, server_name: str, archive: Path) -> BackupInfo:
        identifier = archive.stem
        stat = archive.stat()
        data = self._read_sidecar(archive)
        if data is not None:
            created_at = str(data.get("created_at") or _timestamp_from_identifier(identifier))
            return BackupInfo(
                identifier=identifier,
                path=archive,
                created_at=created_at,
                size_bytes=stat.st_size,
                server=str(data.get("server") or server_name),
                project=str(data.get("project") or ""),
                minecraft_version=str(data.get("minecraft_version") or ""),
                build=int(data.get("build") or 0),
                note=str(data.get("note") or ""),
                files=int(data.get("files") or 0),
            )
        created_at = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(
            timespec="seconds"
        )
        return BackupInfo(
            identifier=identifier,
            path=archive,
            created_at=created_at,
            size_bytes=stat.st_size,
            server=server_name,
        )

    @staticmethod
    def _read_sidecar(archive: Path) -> dict[str, Any] | None:
        sidecar = archive.with_suffix(_SIDECAR_SUFFIX)
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _write_sidecar(archive: Path, manifest: dict[str, Any]) -> None:
        sidecar = archive.with_suffix(_SIDECAR_SUFFIX)
        temporary = sidecar.with_name(sidecar.name + ".tmp")
        temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, sidecar)

    @staticmethod
    def _validate_members(names: builtins.list[str]) -> None:
        for name in names:
            normalized = name.replace("\\", "/")
            pure = PurePosixPath(normalized)
            if (
                pure.is_absolute()
                or ".." in pure.parts
                or re.match(r"^[A-Za-z]:", normalized)
            ):
                raise BackupError(
                    f"Backup contains an unsafe path: {name!r}",
                    hint="Do not restore this archive; it may have been tampered with.",
                )

    @staticmethod
    def _restore_latest_log(logs_source: Path, server_dir: Path) -> int:
        source = logs_source / "latest.log"
        if not source.is_file():
            return 0
        target = server_dir / "logs" / "latest.log"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return 1

    @staticmethod
    def _replace_directory(source: Path, target: Path) -> int:
        if target.exists() or target.is_symlink():
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.copytree(source, target)
        return sum(1 for path in target.rglob("*") if path.is_file())

    @staticmethod
    def _replace_file(source: Path, target: Path) -> int:
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return 1


__all__ = [
    "COMPRESSION_FILTERS",
    "FORMAT_VERSION",
    "MANIFEST_NAME",
    "BackupInfo",
    "BackupManager",
]
