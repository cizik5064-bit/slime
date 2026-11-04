"""Minecraft server process management with a live console."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TextIO

from .errors import ServerError
from .models import Project, Server

_READY_RE = re.compile(r"(Done \(|Listening on /|Done in |Done \()", re.IGNORECASE)
_LINE_LIMIT = 3000

# Flags that Minecraft/Paper error messages suggest as a recovery step.
_RECOVERY_FLAGS = {
    "--forceupgrade": "--forceUpgrade",
    "--erasecache": "--eraseCache",
    "--recreateregionfiles": "--recreateRegionFiles",
    "--safemode": "--safeMode",
}
_FLAG_RE = re.compile(r"--[A-Za-z][\w-]*")
_FAILURE_RE = re.compile(
    r"\b(?:error|warn(?:ing)?|failed|failure|cannot|can't|unable|corrupt|broken)\b",
    re.IGNORECASE,
)
# Lines that look like a Java exception or stack trace. Used to mark a process
# as crashed even when Java exits with status 0 after printing a throwable.
_EXCEPTION_LINE_RE = re.compile(
    r"(?:^|\s)(?:[\w$]+\.)+[\w$]*(?:Exception|Error|Throwable)\b"
    r"|Exception in thread\b"
    r"|Uncaught exception\b"
    r"|^\s*Caused by:"
    r"|^\s*Suppressed:"
    r"|^\s*at\s+[\w$./]+(?:\(|\.)"
)


def suggested_arguments(line: str) -> list[str]:
    """Return recovery arguments suggested by a server error or warning line.

    Minecraft and Paper mention recovery flags in plain text, for example
    ``reset to vanilla with --safeMode``. Only a small allow-list is
    considered so unrelated flags in plugin output are ignored.
    """
    if not _FAILURE_RE.search(line):
        return []
    found: list[str] = []
    for match in _FLAG_RE.finditer(line):
        flag = match.group(0)
        canonical = _RECOVERY_FLAGS.get(flag.lower())
        if canonical is not None and canonical not in found:
            found.append(canonical)
    return found


class ServerState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CRASHED = "crashed"


LineListener = Callable[[str], None]
StateListener = Callable[[ServerState], None]
ExitListener = Callable[[int], None]
RecoveryListener = Callable[[list[str]], None]


class ServerProcess:
    """Owns one Java process and its console stream.

    The process is intentionally tied to the lifetime of the Slime process that
    started it: the CLI runs a server in the foreground, and the TUI keeps it in
    memory while the app is open. This avoids orphaned servers and makes
    console I/O reliable on Windows, where attaching to another process's stdin
    is not possible without RCON.
    """

    def __init__(
        self,
        server: Server,
        server_dir: Path,
        java_path: str | Path,
        *,
        log_dir: Path,
        extra_args: list[str] | None = None,
        command_override: list[str] | None = None,
        java_home: str | Path | None = None,
        on_recovery: RecoveryListener | None = None,
    ) -> None:
        self.server = server
        self.server_dir = Path(server_dir)
        self.java_path = Path(java_path)
        self.log_dir = Path(log_dir)
        self.extra_args = list(extra_args if extra_args is not None else server.extra_args)
        self.command_override = command_override
        self.java_home = Path(java_home) if java_home is not None else None
        self._recovery_listener = on_recovery
        self.recovery_args: list[str] = []

        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._state = ServerState.STOPPED
        self._exit_code: int | None = None
        self._lines: deque[str] = deque(maxlen=_LINE_LIMIT)
        self._line_listeners: list[LineListener] = []
        self._state_listeners: list[StateListener] = []
        self._exit_listeners: list[ExitListener] = []
        self._log_handle: TextIO | None = None
        self._started_at: datetime | None = None
        self._saw_exception = False

    # --------------------------------------------------------------- listeners
    def add_line_listener(self, listener: LineListener) -> None:
        if listener not in self._line_listeners:
            self._line_listeners.append(listener)

    def remove_line_listener(self, listener: LineListener) -> None:
        with contextlib.suppress(ValueError):
            self._line_listeners.remove(listener)

    def add_state_listener(self, listener: StateListener) -> None:
        if listener not in self._state_listeners:
            self._state_listeners.append(listener)

    def remove_state_listener(self, listener: StateListener) -> None:
        with contextlib.suppress(ValueError):
            self._state_listeners.remove(listener)

    def add_exit_listener(self, listener: ExitListener) -> None:
        if listener not in self._exit_listeners:
            self._exit_listeners.append(listener)

    def remove_exit_listener(self, listener: ExitListener) -> None:
        with contextlib.suppress(ValueError):
            self._exit_listeners.remove(listener)

    # ---------------------------------------------------------------- properties
    @property
    def state(self) -> ServerState:
        return self._state

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def started_at(self) -> datetime | None:
        return self._started_at

    @property
    def lines(self) -> list[str]:
        return list(self._lines)

    def uptime(self) -> float:
        if self._started_at is None:
            return 0.0
        return max(0.0, (datetime.now(UTC) - self._started_at).total_seconds())

    # -------------------------------------------------------------------- start
    def build_command(self) -> list[str]:
        if self.command_override is not None:
            return list(self.command_override)
        min_memory = self.server.min_memory_mb or self.server.memory_mb
        command = [
            str(self.java_path),
            f"-Xms{min_memory}M",
            f"-Xmx{self.server.memory_mb}M",
            "-Dfile.encoding=UTF-8",
        ]
        if self.server.cpu_cores is not None:
            command.append(f"-XX:ActiveProcessorCount={self.server.cpu_cores}")
        command.extend(["-jar", self.server.jar_file])
        if not self.server.is_proxy:
            command.append("nogui")
        command.extend(self.extra_args)
        return command

    async def start(self) -> None:
        if self._state in (ServerState.STARTING, ServerState.RUNNING, ServerState.STOPPING):
            raise ServerError(f"Server '{self.server.name}' is already running.")
        if self.command_override is None:
            if not self.java_path.is_file():
                raise ServerError(
                    f"Java executable not found: {self.java_path}",
                    hint=f"Install Java with: slime java install {self.server.java_major}",
                )
            jar = self.server_dir / self.server.jar_file
            if not jar.is_file():
                raise ServerError(
                    f"Server jar not found: {jar}",
                    hint="Recreate the server or download the jar manually.",
                )

        self.server_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / f"{self.server.name}.log"
        try:
            self._log_handle = log_path.open("a", encoding="utf-8", errors="replace")
            stamp = datetime.now(UTC).isoformat(timespec="seconds")
            self._log_handle.write(f"\n=== {stamp} starting {self.server.name} ===\n")
            self._log_handle.flush()
        except OSError:
            self._log_handle = None

        environment = os.environ.copy()
        if self.command_override is None:
            java_home = self.java_home or self.java_path.parent.parent
            environment["JAVA_HOME"] = str(java_home)

        self._set_state(ServerState.STARTING)
        self._exit_code = None
        self._saw_exception = False
        self._started_at = datetime.now(UTC)
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.build_command(),
                cwd=str(self.server_dir),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=environment,
            )
        except OSError as exc:
            self._close_log()
            self._set_state(ServerState.STOPPED)
            raise ServerError(
                f"Could not start '{self.server.name}': {exc}",
                hint="Check that Java is installed and the server directory is writable.",
            ) from exc

        self._write_pid()
        self._apply_cpu_affinity()
        self._reader_task = asyncio.create_task(self._pump(), name=f"slime-console-{self.server.name}")

    def _apply_cpu_affinity(self) -> None:
        """Best-effort OS-level CPU affinity, in addition to ActiveProcessorCount."""
        cores = self.server.cpu_cores
        if cores is None or self._process is None or self._process.pid is None:
            return
        with contextlib.suppress(Exception):
            import psutil

            process = psutil.Process(self._process.pid)
            current = process.cpu_affinity()
            if current:
                process.cpu_affinity(current[:cores])

    def _write_pid(self) -> None:
        if self.pid is None:
            return
        with contextlib.suppress(OSError):
            (self.server_dir / "slime.pid").write_text(f"{self.pid}\n", encoding="utf-8")

    def _clear_pid(self) -> None:
        (self.server_dir / "slime.pid").unlink(missing_ok=True)

    # --------------------------------------------------------------------- pump
    async def _pump(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        cancelled = False
        try:
            while True:
                raw = await process.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                self._lines.append(line)
                if self._log_handle is not None:
                    try:
                        self._log_handle.write(line + "\n")
                        self._log_handle.flush()
                    except OSError:
                        pass
                if self._state is ServerState.STARTING and _READY_RE.search(line):
                    self._set_state(ServerState.RUNNING)
                if _EXCEPTION_LINE_RE.search(line):
                    self._saw_exception = True
                new_recovery_args = [
                    argument
                    for argument in suggested_arguments(line)
                    if argument not in self.recovery_args
                ]
                if new_recovery_args:
                    self.recovery_args.extend(new_recovery_args)
                    if self._recovery_listener is not None:
                        with contextlib.suppress(Exception):
                            self._recovery_listener(list(self.recovery_args))
                for line_listener in list(self._line_listeners):
                    try:
                        line_listener(line)
                    except Exception:  # pragma: no cover - listener bugs
                        continue
            await process.wait()
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            if not cancelled:
                final_code = (
                    self._exit_code if self._exit_code is not None else process.returncode
                )
                if final_code is None:
                    final_code = 0
                self._exit_code = final_code
            self._clear_pid()
            self._close_log()
            if not cancelled:
                user_stopped = self._state is ServerState.STOPPING
                crashed = not user_stopped and (
                    self._exit_code != 0 or self._saw_exception
                )
                self._set_state(
                    ServerState.CRASHED if crashed else ServerState.STOPPED
                )
                for exit_listener in list(self._exit_listeners):
                    try:
                        exit_listener(self._exit_code or 0)
                    except Exception:  # pragma: no cover
                        continue

    def _close_log(self) -> None:
        if self._log_handle is not None:
            with contextlib.suppress(OSError):
                self._log_handle.close()
            self._log_handle = None

    # ------------------------------------------------------------------ console
    async def send(self, command: str) -> None:
        command = command.strip()
        if not command:
            return
        if not self.is_running or self._process is None or self._process.stdin is None:
            raise ServerError(f"Server '{self.server.name}' is not running.")
        try:
            self._process.stdin.write((command + "\n").encode("utf-8"))
            await self._process.stdin.drain()
        except (OSError, RuntimeError) as exc:
            raise ServerError(f"Could not send command to the server: {exc}") from exc

    # --------------------------------------------------------------------- stop
    async def stop(self, timeout: float = 30.0) -> None:
        if not self.is_running or self._process is None:
            self._set_state(ServerState.STOPPED)
            return
        self._set_state(ServerState.STOPPING)
        with contextlib.suppress(ServerError):
            await self.send(self._stop_command())
        try:
            await asyncio.wait_for(self.wait(), timeout=timeout)
            return
        except TimeoutError:
            pass
        with contextlib.suppress(ProcessLookupError, OSError):
            self._process.terminate()
        try:
            await asyncio.wait_for(self.wait(), timeout=10)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError, OSError):
                self._process.kill()
            await self.wait()

    def _stop_command(self) -> str:
        """Return the console command that shuts this server kind down."""
        if self.server.project is Project.VELOCITY:
            return "shutdown"
        if self.server.project is Project.WATERFALL:
            return "end"
        return "stop"

    async def wait(self) -> int:
        if self._process is None:
            return self._exit_code if self._exit_code is not None else 0
        code = await self._process.wait()
        if self._exit_code is None:
            self._exit_code = code
        return code

    def terminate_now(self) -> None:
        """Best-effort synchronous termination, used when the app is closing."""
        if self._process is not None and self._process.returncode is None:
            with contextlib.suppress(ProcessLookupError, OSError):
                self._process.terminate()

    async def force_kill(self) -> None:
        """Immediately kill the process, skipping the graceful shutdown sequence.

        Used when the server is unresponsive (e.g. stuck on STOPPING, or not
        answering stdin) and the user wants out now rather than waiting for
        the stop() timeout chain to run its course.
        """
        if self._process is None or self._process.returncode is not None:
            self._set_state(ServerState.STOPPED)
            return
        self._set_state(ServerState.STOPPING)
        with contextlib.suppress(ProcessLookupError, OSError):
            self._process.kill()
        await self.wait()

    # -------------------------------------------------------------------- state
    def _set_state(self, state: ServerState) -> None:
        if state is self._state:
            return
        self._state = state
        for listener in list(self._state_listeners):
            try:
                listener(state)
            except Exception:  # pragma: no cover
                continue

    async def __aenter__(self) -> ServerProcess:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()
