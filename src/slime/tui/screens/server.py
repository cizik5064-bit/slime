"""Per-server screen: status, controls and live console."""

from __future__ import annotations

import asyncio
import contextlib
import re
from typing import TYPE_CHECKING, ClassVar

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Button, Footer, Header, Input, RichLog, Static

from ...errors import SlimeError
from ...models import Server
from ...process import ServerState
from .backup import BackupScreen
from .confirm import ConfirmScreen, HoldConfirmScreen
from .edit import EditServerScreen

if TYPE_CHECKING:
    from ..app import SlimeApp

_STATE_COLORS = {
    ServerState.RUNNING: "green",
    ServerState.STARTING: "yellow",
    ServerState.STOPPING: "yellow",
    ServerState.CRASHED: "red",
    ServerState.STOPPED: "dim",
}

# Paper/Vanilla/Velocity log lines carry their level as a bare word inside
# the bracketed prefix - "[10:37:03 ERROR]:", "[Server thread/WARN]:",
# "[12:00:00 INFO]:". Modern Paper does not emit ANSI color codes over a
# piped stdout (it detects the non-tty and disables jline's terminal color
# support entirely - confirmed: a captured run has zero 0x1B bytes), so
# Slime colors the console itself by matching the level word, same as a
# real terminal with log highlighting would.
_LOG_LEVEL_RE = re.compile(r"\b(FATAL|ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE)\b")
_LOG_LEVEL_COLORS = {
    "FATAL": "bold red",
    "ERROR": "red",
    "WARN": "yellow",
    "WARNING": "yellow",
    "INFO": "white",
    "DEBUG": "dim cyan",
    "TRACE": "dim",
}

# Stack traces are printed without a log-level prefix. Match the usual Java
# throwable shapes so exception lines get the same red as ERROR lines.
_EXCEPTION_RE = re.compile(
    r"^(?:"
    r"\s*at\s+[\w$./]+(?:\.[\w$<>]+)*\("
    r"|\s*Caused by:"
    r"|\s*Suppressed:"
    r"|\s*\.\.\.\s+\d+\s+more\s*$"
    r"|\s*Exception in thread\b"
    r"|\s*(?:[\w$]+\.)+[A-Z][\w$]*(?:Exception|Error|Throwable)\b"
    r"|\s*(?:[A-Z][\w$]*Exception|AssertionError|OutOfMemoryError)\b"
    r")"
)
_SLIME_PREFIX_RE = re.compile(r"^\[slime\]", re.IGNORECASE)
_DONE_RE = re.compile(r"\bDone!?(?:\s*\([^)]*\)!?)?", re.IGNORECASE)


def slime_message(message: str) -> str:
    """Format a console line that comes from Slime itself."""
    return f"[slime] {message}"


def _colorize_log_line(line: str) -> Text:
    """Color a server console line by its log level and special markers.

    Slime's own ``[slime]`` prefix is bold bright green. The ``Done`` line that
    signals a successful server start gets the same highlight. Everything else
    follows the normal log-level colors.
    """
    base_style: str | None = None
    slime_prefix = _SLIME_PREFIX_RE.match(line)
    if slime_prefix is None:
        match = _LOG_LEVEL_RE.search(line)
        if match is not None:
            base_style = _LOG_LEVEL_COLORS[match.group(1)]
        elif _EXCEPTION_RE.match(line):
            base_style = "red"
    text = Text(line, style=base_style) if base_style is not None else Text(line)
    if slime_prefix is not None:
        text.stylize("bold bright_green", slime_prefix.start(), slime_prefix.end())
    done = _DONE_RE.search(line)
    if done is not None:
        text.stylize("bold bright_green", done.start(), done.end())
    return text


class ServerScreen(Screen):
    """Full-screen view of one server."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("escape", "back", "Back")
    ]

    def __init__(self, app: SlimeApp, server: Server) -> None:
        super().__init__()
        self.slime = app
        self.server = server
        self._line_listener = self.append_line
        self._state_listener = self.on_process_state
        self._status_timer: Timer | None = None
        self._external_noted = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="server-body"):
            yield Static("", id="server-title")
            yield Static("", id="server-status")
            with Horizontal(id="server-buttons"):
                yield Button("Start", id="toggle", variant="success")
                yield Button("Kill", id="kill", variant="error")
                yield Button("Restart", id="restart", variant="primary")
                yield Button("Backups", id="backups")
                yield Button("Edit", id="edit")
                yield Button("Back", id="back")
            yield RichLog(
                id="console",
                highlight=False,
                markup=False,
                wrap=True,
                max_lines=5000,
            )
            yield Input(
                placeholder="Type a server command and press Enter…",
                id="command",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.update_title()
        process = self.slime.get_process(self.server.name)
        if process is not None:
            for line in process.lines:
                self.append_line(line)
            process.add_line_listener(self._line_listener)
            process.add_state_listener(self._state_listener)
        self.update_status()
        # Detect servers started by another Slime process or a plain CLI.
        self._status_timer = self.set_interval(2.0, self.update_status)

    def on_unmount(self) -> None:
        if self._status_timer is not None:
            self._status_timer.stop()
            self._status_timer = None
        process = self.slime.get_process(self.server.name)
        if process is not None:
            process.remove_line_listener(self._line_listener)
            process.remove_state_listener(self._state_listener)

    def update_title(self) -> None:
        min_memory = self.server.min_memory_mb or self.server.memory_mb
        memory = (
            f"{min_memory}-{self.server.memory_mb} MB"
            if min_memory != self.server.memory_mb
            else f"{self.server.memory_mb} MB"
        )
        self.query_one("#server-title", Static).update(
            f"[bold]{escape(self.server.name)}[/bold] · {self.server.project.display_name} "
            f"{escape(self.server.minecraft_version)} (build {self.server.build}) · "
            f"{memory} · port {self.server.port}"
        )

    # ---------------------------------------------------------------- console
    def append_line(self, line: str) -> None:
        with contextlib.suppress(Exception):
            # _colorize_log_line builds a rich.Text directly from the level
            # word it finds - never through rich markup parsing - so a
            # server line containing literal "[foo]" can't inject markup.
            self.query_one("#console", RichLog).write(_colorize_log_line(line))

    def on_process_state(self, state: ServerState) -> None:
        # The app already shows the crash notification; only refresh the UI here.
        self.update_status(state)

    def _is_external_running(self) -> bool:
        process = self.slime.get_process(self.server.name)
        if process is not None and process.is_running:
            return False
        running, pid = self.slime.store.is_running(self.server.name)
        if process is not None and pid is not None and pid == process.pid:
            # A stale PID file from the process this Slime instance owns.
            return False
        return running

    def update_status(self, state: ServerState | None = None) -> None:
        process = self.slime.get_process(self.server.name)
        external = False
        pid: int | None = None
        running, external_pid = self.slime.store.is_running(self.server.name)
        stale_local = (
            process is not None
            and external_pid is not None
            and external_pid == process.pid
        )
        local_active = process is not None and (
            process.is_running
            or process.state in {ServerState.STARTING, ServerState.STOPPING}
        )
        if local_active and process is not None:
            actual = state if state is not None else process.state
            pid = process.pid if process.is_running else None
        elif running and not stale_local:
            actual = ServerState.RUNNING
            pid = external_pid
            external = True
        elif process is not None:
            actual = state if state is not None else process.state
        else:
            actual = state if state is not None else ServerState.STOPPED
        color = _STATE_COLORS[actual]
        detail = f" · pid {pid}" if pid else ""
        if external:
            detail = f" · external{detail}"
        self.query_one("#server-status", Static).update(
            f"[{color}]{actual.value.upper()}[/{color}]{detail}"
        )
        if external and not self._external_noted:
            self._external_noted = True
            self.append_line(
                slime_message(
                    "Server is running in another process. "
                    "Commands and Stop use RCON."
                )
            )

        toggle = self.query_one("#toggle", Button)
        if actual in {ServerState.RUNNING, ServerState.STARTING}:
            toggle.label = "Stop"
            toggle.variant = "warning"
            toggle.disabled = False
        elif actual is ServerState.STOPPING:
            # Already shutting down - Kill is the only way to act on it now.
            toggle.label = "Stop"
            toggle.variant = "warning"
            toggle.disabled = True
        else:
            toggle.label = "Start"
            toggle.variant = "success"
            toggle.disabled = False
        self.query_one("#kill", Button).disabled = external or actual not in {
            ServerState.RUNNING,
            ServerState.STARTING,
            ServerState.STOPPING,
        }
        self.query_one("#restart", Button).disabled = external or (
            actual is not ServerState.RUNNING
        )
        self.query_one("#command", Input).disabled = actual is not ServerState.RUNNING

    # ----------------------------------------------------------------- actions
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "toggle":
            if self._is_external_running():
                await self.stop_server()
                return
            process = self.slime.get_process(self.server.name)
            if process is not None and process.state in {
                ServerState.RUNNING,
                ServerState.STARTING,
            }:
                await self.stop_server()
            else:
                await self.start_server()
        elif button_id == "kill":
            if self._is_external_running():
                self.slime.notify(
                    "Kill is only available for servers started by this Slime instance.",
                    severity="warning",
                )
                return
            await self.kill_server()
        elif button_id == "restart":
            if self._is_external_running():
                self.slime.notify(
                    "Restart is only available for servers started by this Slime "
                    "instance. Use Stop, then Start.",
                    severity="warning",
                )
                return
            await self.restart_server()
        elif button_id == "edit":
            self.open_editor()
        elif button_id == "backups":
            self.open_backups()
        elif button_id == "back":
            self.action_back()

    async def start_server(self, extra_args: list[str] | None = None) -> None:
        if self._is_external_running():
            self.slime.notify(
                "Server is already running in another process. Use Stop to shut "
                "it down through RCON.",
                severity="warning",
            )
            self.update_status()
            return
        if extra_args is None and self.server.world_reset_suggested:
            self.slime.push_screen(
                HoldConfirmScreen(
                    f"The previous crash suggests that the world of "
                    f"'{self.server.name}' is damaged.\n\n"
                    "Resetting deletes the overworld, nether and end. "
                    "This cannot be undone.",
                    cancel_label="Keep world",
                ),
                self._on_world_reset_choice,
            )
            return
        if extra_args is None and self.server.recovery_args:
            suggestion = list(self.server.recovery_args)
            flags = " ".join(suggestion)
            self.slime.push_screen(
                ConfirmScreen(
                    f"The previous run ended with an error that suggests starting "
                    f"with {flags}.\n\nStart with it?",
                    confirm_label=f"Start with {flags}",
                    cancel_label="Start without",
                    danger=False,
                ),
                lambda confirmed: self._on_recovery_choice(confirmed, suggestion),
            )
            return
        try:
            process = await self.slime.start_server(self.server, extra_args=extra_args)
        except SlimeError as error:
            self.slime.notify_error(error)
            return
        process.add_line_listener(self._line_listener)
        process.add_state_listener(self._state_listener)
        for line in process.lines:
            self.append_line(line)
        self.append_line(slime_message(f"Starting {self.server.name}..."))
        self.update_status(process.state)

    def _on_world_reset_choice(self, confirmed: bool | None) -> None:
        self.server.world_reset_suggested = False
        self._save_server()
        if confirmed:
            self.slime.run_worker(
                self._reset_world_and_start(),
                exclusive=True,
                group="start",
                exit_on_error=False,
            )
            return
        self.slime.run_worker(
            self.start_server(), exclusive=True, group="start", exit_on_error=False
        )

    async def _reset_world_and_start(self) -> None:
        try:
            removed = await asyncio.to_thread(
                self.slime.store.reset_world, self.server.name
            )
        except OSError as error:
            self.slime.notify_error(error)
            return
        if removed:
            self.append_line(
                slime_message(f"World reset: removed {len(removed)} folder(s).")
            )
        else:
            self.append_line(slime_message("No world folders found."))
        await self.start_server()

    def _on_recovery_choice(self, confirmed: bool | None, args: list[str]) -> None:
        transient = [*self.server.extra_args, *args] if confirmed else None
        # Recovery flags apply to this launch only; never persist them.
        self.server.recovery_args = []
        self._save_server()
        self.slime.run_worker(
            self.start_server(transient),
            exclusive=True,
            group="start",
            exit_on_error=False,
        )

    def _save_server(self) -> None:
        with contextlib.suppress(SlimeError, OSError):
            self.slime.store.save(self.server)

    async def stop_server(self) -> None:
        self.append_line(slime_message("Stopping server..."))
        try:
            await self.slime.stop_server(self.server.name)
        except SlimeError as error:
            self.slime.notify_error(error)
            self.update_status()
            return
        self.append_line(slime_message("Server stopped."))
        self.update_status(ServerState.STOPPED)

    async def kill_server(self) -> None:
        process = self.slime.get_process(self.server.name)
        if process is None:
            self.update_status(ServerState.STOPPED)
            return
        self.append_line(slime_message(f"Killing {self.server.name}..."))
        await process.force_kill()
        self.append_line(slime_message("Server stopped."))
        self.update_status(ServerState.STOPPED)

    async def restart_server(self) -> None:
        process = self.slime.get_process(self.server.name)
        if process is None or process.state is not ServerState.RUNNING:
            return
        self.append_line(slime_message("Restarting server..."))
        await self.stop_server()
        await self.start_server()

    def open_editor(self) -> None:
        self.slime.push_screen(
            EditServerScreen(self.slime, self.server),
            self._after_edit,
        )

    def open_backups(self) -> None:
        self.slime.push_screen(BackupScreen(self.slime, self.server))

    def _after_edit(self, result: Server | str | None) -> None:
        if result == "deleted":
            self.slime.refresh_dashboard()
            self.slime.pop_screen()
            return
        if isinstance(result, Server):
            self.server = result
            self.update_title()
            self.slime.refresh_dashboard()
            self.slime.notify(
                "Settings saved. Restart the server to apply runtime changes.",
                timeout=4,
            )

    # ------------------------------------------------------------------ input
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        if not command:
            return
        event.input.value = ""
        process = self.slime.get_process(self.server.name)
        if process is not None and process.is_running:
            try:
                await process.send(command)
            except SlimeError as error:
                self.slime.notify_error(error)
                return
            self.append_line(f"> {command}")
            return

        if not self.slime.store.is_running(self.server.name)[0]:
            self.slime.notify("The server is not running.", severity="warning")
            self.update_status()
            return
        self.append_line(f"> {command}")
        try:
            output = await self.slime.send_remote_command(self.server, command)
        except SlimeError as error:
            self.slime.notify_error(error)
            return
        for line in output.splitlines():
            self.append_line(line)

    def action_back(self) -> None:
        self.slime.pop_screen()


__all__ = ["ServerScreen"]
