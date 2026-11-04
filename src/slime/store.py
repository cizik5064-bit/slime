"""On-disk server registry."""

from __future__ import annotations

import contextlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import psutil

from .config import Config
from .errors import ServerError, ValidationError
from .models import Server, validate_server_name

METADATA_FILE = "slime.json"
PID_FILE = "slime.pid"


class ServerStore:
    """Reads and writes ``servers/<name>/slime.json`` records."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.root = config.paths.servers

    # ------------------------------------------------------------------ paths
    def path(self, name: str) -> Path:
        return self.root / validate_server_name(name)

    def metadata_path(self, name: str) -> Path:
        return self.path(name) / METADATA_FILE

    def pid_path(self, name: str) -> Path:
        return self.path(name) / PID_FILE

    def exists(self, name: str) -> bool:
        return self.metadata_path(name).is_file()

    # ------------------------------------------------------------------- read
    def list(self) -> list[Server]:
        servers: list[Server] = []
        if not self.root.exists():
            return servers
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            metadata = directory / METADATA_FILE
            if not metadata.is_file():
                continue
            try:
                servers.append(self._read(metadata))
            except (ServerError, ValidationError, OSError, ValueError):
                # A broken record should not make the whole list unusable.
                continue
        return servers

    def get(self, name: str) -> Server:
        metadata = self.metadata_path(name)
        if not metadata.is_file():
            raise ServerError(
                f"Server '{name}' does not exist.",
                hint="Run `slime server list` to see configured servers.",
            )
        return self._read(metadata)

    @staticmethod
    def _read(metadata: Path) -> Server:
        try:
            data = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ServerError(
                f"Cannot read server metadata at {metadata}: {exc}",
                hint="Fix the JSON file or delete the server directory.",
            ) from exc
        return Server.from_dict(data)

    # ------------------------------------------------------------------ write
    def save(self, server: Server) -> None:
        directory = self.path(server.name)
        directory.mkdir(parents=True, exist_ok=True)
        metadata = directory / METADATA_FILE
        temporary = metadata.with_name(metadata.name + ".tmp")
        temporary.write_text(
            json.dumps(server.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(metadata)

    # ---------------------------------------------------------------- create
    def create_directory(self, name: str) -> Path:
        directory = self.path(name)
        if directory.exists():
            if not directory.is_dir():
                raise ServerError(
                    f"{directory} already exists but is not a directory.",
                    hint="Choose another server name or remove the conflicting file.",
                )
            try:
                not_empty = any(directory.iterdir())
            except OSError as exc:
                raise ServerError(
                    f"Cannot inspect {directory}: {exc}",
                    hint="Check permissions or choose another server name.",
                ) from exc
            if not_empty:
                raise ServerError(
                    f"Directory {directory} already exists and is not empty.",
                    hint="Choose another server name or remove the directory.",
                )
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    # ---------------------------------------------------------------- rename
    def rename(self, old_name: str, new_name: str) -> Path:
        """Move a server directory to a new name.

        The caller is responsible for updating the ``Server`` object and
        saving its metadata after the directory has been moved.
        """
        old_directory = self.path(old_name)
        new_directory = self.path(new_name)
        if old_directory == new_directory:
            return new_directory
        if not old_directory.is_dir():
            raise ServerError(f"Server '{old_name}' does not exist.")
        if new_directory.exists():
            raise ServerError(
                f"Server '{new_name}' already exists.",
                hint="Choose another server name.",
            )
        try:
            old_directory.rename(new_directory)
        except OSError as exc:
            raise ServerError(
                f"Cannot rename '{old_name}' to '{new_name}': {exc}",
                hint="Stop the server first and check directory permissions.",
            ) from exc
        return new_directory

    # ---------------------------------------------------------------- delete
    def delete(self, name: str, *, keep_files: bool = False) -> None:
        server = self.get(name)
        directory = self.path(server.name)
        if keep_files:
            self.metadata_path(server.name).unlink(missing_ok=True)
            self.pid_path(server.name).unlink(missing_ok=True)
            return
        shutil.rmtree(directory)

    # ------------------------------------------------------------------- pid
    def read_pid(self, name: str) -> int | None:
        path = self.pid_path(name)
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def is_running(self, name: str) -> tuple[bool, int | None]:
        """Return ``(running, pid)`` based on the PID file and process table."""
        pid = self.read_pid(name)
        if pid is None:
            return False, None
        try:
            process = psutil.Process(pid)
            if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                return False, pid
            # Guard against PID reuse: a stale PID file should not report an
            # unrelated process as our server.
            if "java" not in process.name().lower():
                return False, pid
            if not self._matches_server(process, name):
                return False, pid
            return True, pid
        except psutil.Error:
            return False, pid

    def _matches_server(self, process: psutil.Process, name: str) -> bool:
        """Check that a live PID really belongs to the server directory.

        A reused PID may point at any Java process. Compare its working
        directory and command line with the server's own directory instead of
        trusting the process name alone.
        """
        directory = self.path(name)
        try:
            cwd = process.cwd()
        except (psutil.Error, OSError):
            cwd = None
        if cwd:
            try:
                if Path(cwd).resolve() == directory.resolve():
                    return True
            except OSError:
                pass

        try:
            command = " ".join(process.cmdline())
        except (psutil.Error, OSError):
            return False
        if not command:
            return False

        normalized = command.replace("\\", "/").lower()
        try:
            directory_text = str(directory.resolve()).replace("\\", "/").lower()
        except OSError:
            directory_text = str(directory).replace("\\", "/").lower()
        if directory_text and directory_text in normalized:
            return True

        jar_file = "server.jar"
        with contextlib.suppress(ServerError, ValidationError, OSError, ValueError):
            jar_file = self._read(self.metadata_path(name)).jar_file
        return (
            jar_file.lower() in normalized
            and directory.name.lower() in normalized
        )

    def clear_pid(self, name: str) -> None:
        self.pid_path(name).unlink(missing_ok=True)

    def write_pid(self, name: str, pid: int) -> None:
        path = self.pid_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{pid}\n", encoding="utf-8")

    @staticmethod
    def utc_now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")
