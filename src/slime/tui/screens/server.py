"""Per-server screen: status, controls and live console."""

from __future__ import annotations

import asyncio
import contextlib
import re
from typing import TYPE_CHECKING, ClassVar

from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, RichLog, Static

from ...errors import SlimeError
from ...models import Server
from ...process import ServerState
from .confirm import ConfirmScreen
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


def _colorize_log_line(line: str) -> Text:
    """Color a whole server console line by its log level, found anywhere
    in the bracketed prefix ("[10:37:03 ERROR]:", "[Server thread/WARN]:").
    Stack trace and exception lines, which have no level prefix, are colored
    red like ERROR. Falls back to plain text for everything else."""
    match = _LOG_LEVEL_RE.search(line)
    if match is not None:
        color = _LOG_LEVEL_COLORS[match.group(1)]
        return Text(line, style=color)
    if _EXCEPTION_RE.match(line):
        return Text(line, style="red")
    return Text(line)


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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="server-body"):
            yield Static("", id="server-title")
            yield Static("", id="server-status")
            with Horizontal(id="server-buttons"):
                yield Button("Start", id="toggle", variant="success")
                yield Button("Kill", id="kill", variant="error")
                yield Button("Restart", id="restart")
                yield Button("Edit", id="edit")
                yield Button("Delete", id="delete", variant="error")
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
            self.update_status(process.state)
        else:
            self.update_status(ServerState.STOPPED)

    def on_unmount(self) -> None:
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
        self.update_status(state)
        if state is ServerState.CRASHED:
            self.slime.notify(
                f"Server '{self.server.name}' crashed. Check the console output.",
                severity="error",
                timeout=8,
            )

    def update_status(self, state: ServerState | None = None) -> None:
        process = self.slime.get_process(self.server.name)
        if state is None:
            state = process.state if process is not None else ServerState.STOPPED
        color = _STATE_COLORS[state]
        pid = f" · pid {process.pid}" if process is not None and process.pid else ""
        self.query_one("#server-status", Static).update(
            f"[{color}]{state.value.upper()}[/{color}]{pid}"
        )

        toggle = self.query_one("#toggle", Button)
        if state in {ServerState.RUNNING, ServerState.STARTING}:
            toggle.label = "Stop"
            toggle.variant = "warning"
            toggle.disabled = False
        elif state is ServerState.STOPPING:
            # Already shutting down - Kill is the only way to act on it now.
            toggle.label = "Stop"
            toggle.variant = "warning"
            toggle.disabled = True
        else:
            toggle.label = "Start"
            toggle.variant = "success"
            toggle.disabled = False
        self.query_one("#kill", Button).disabled = state not in {
            ServerState.RUNNING,
            ServerState.STARTING,
            ServerState.STOPPING,
        }
        self.query_one("#restart", Button).disabled = state in {
            ServerState.STARTING,
            ServerState.STOPPING,
        }
        self.query_one("#command", Input).disabled = state is not ServerState.RUNNING

    # ----------------------------------------------------------------- actions
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "toggle":
            process = self.slime.get_process(self.server.name)
            if process is not None and process.state in {
                ServerState.RUNNING,
                ServerState.STARTING,
            }:
                await self.stop_server()
            else:
                await self.start_server()
        elif button_id == "kill":
            await self.kill_server()
        elif button_id == "restart":
            await self.restart_server()
        elif button_id == "edit":
            self.open_editor()
        elif button_id == "delete":
            self.confirm_delete()
        elif button_id == "back":
            self.action_back()

    async def start_server(self) -> None:
        if self.server.recovery_args:
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
            process = await self.slime.start_server(self.server)
        except SlimeError as error:
            self.slime.notify_error(error)
            return
        process.add_line_listener(self._line_listener)
        process.add_state_listener(self._state_listener)
        for line in process.lines:
            self.append_line(line)
        self.append_line(f"[slime] Starting {self.server.name}…")
        self.update_status(process.state)

    def _on_recovery_choice(self, confirmed: bool | None, args: list[str]) -> None:
        if confirmed:
            self.server.extra_args = list(
                dict.fromkeys([*self.server.extra_args, *args])
            )
        self.server.recovery_args = []
        with contextlib.suppress(SlimeError, OSError):
            self.slime.store.save(self.server)
        self.slime.run_worker(
            self.start_server(), exclusive=True, group="start", exit_on_error=False
        )

    async def stop_server(self) -> None:
        try:
            await self.slime.stop_server(self.server.name)
        except SlimeError as error:
            self.slime.notify_error(error)
            return
        self.update_status(ServerState.STOPPED)

    async def kill_server(self) -> None:
        process = self.slime.get_process(self.server.name)
        if process is None:
            self.update_status(ServerState.STOPPED)
            return
        self.append_line(f"[slime] Force-killing {self.server.name}…")
        await process.force_kill()
        self.update_status(ServerState.STOPPED)

    async def restart_server(self) -> None:
        await self.stop_server()
        await self.start_server()

    def confirm_delete(self) -> None:
        self.slime.push_screen(
            ConfirmScreen(
                f"Delete '{self.server.name}' and all of its world files? "
                "This cannot be undone.",
                confirm_label="Delete server",
            ),
            self._on_delete_confirmed,
        )

    def _on_delete_confirmed(self, confirmed: bool | None) -> None:
        if confirmed:
            self._delete_server()

    def open_editor(self) -> None:
        self.slime.push_screen(
            EditServerScreen(self.slime, self.server),
            self._after_edit,
        )

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

    @work(exclusive=True, group="delete")
    async def _delete_server(self) -> None:
        process = self.slime.get_process(self.server.name)
        try:
            if process is not None and process.is_running:
                await process.stop()
            await asyncio.to_thread(self.slime.store.delete, self.server.name)
        except (SlimeError, OSError) as error:
            self.slime.notify_error(error)
            return
        self.slime.processes.pop(self.server.name, None)
        self.slime.refresh_dashboard()
        self.slime.notify(f"Server '{self.server.name}' deleted.", timeout=4)
        self.slime.pop_screen()

    # ------------------------------------------------------------------ input
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        if not command:
            return
        event.input.value = ""
        process = self.slime.get_process(self.server.name)
        if process is None or not process.is_running:
            self.slime.notify("The server is not running.", severity="warning")
            return
        try:
            await process.send(command)
        except SlimeError as error:
            self.slime.notify_error(error)
            return
        self.append_line(f"> {command}")

    def action_back(self) -> None:
        self.slime.pop_screen()


__all__ = ["ServerScreen"]
