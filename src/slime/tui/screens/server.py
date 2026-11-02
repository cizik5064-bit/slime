"""Per-server screen: status, controls and live console."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, ClassVar

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

if TYPE_CHECKING:
    from ..app import SlimeApp

_STATE_COLORS = {
    ServerState.RUNNING: "green",
    ServerState.STARTING: "yellow",
    ServerState.STOPPING: "yellow",
    ServerState.CRASHED: "red",
    ServerState.STOPPED: "dim",
}


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
                yield Button("Start", id="start", variant="success")
                yield Button("Stop", id="stop", variant="warning")
                yield Button("Restart", id="restart")
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
        self.query_one("#server-title", Static).update(
            f"[bold]{self.server.name}[/bold] · {self.server.project.display_name} "
            f"{self.server.minecraft_version} (build {self.server.build}) · "
            f"{self.server.memory_mb} MB · port {self.server.port}"
        )
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

    # ---------------------------------------------------------------- console
    def append_line(self, line: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#console", RichLog).write(line)

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

        self.query_one("#start", Button).disabled = state in {
            ServerState.RUNNING,
            ServerState.STARTING,
            ServerState.STOPPING,
        }
        self.query_one("#stop", Button).disabled = state not in {
            ServerState.RUNNING,
            ServerState.STARTING,
        }
        self.query_one("#restart", Button).disabled = state in {
            ServerState.STARTING,
            ServerState.STOPPING,
        }
        self.query_one("#command", Input).disabled = state is not ServerState.RUNNING

    # ----------------------------------------------------------------- actions
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "start":
            await self.start_server()
        elif button_id == "stop":
            await self.stop_server()
        elif button_id == "restart":
            await self.restart_server()
        elif button_id == "delete":
            self.confirm_delete()
        elif button_id == "back":
            self.action_back()

    async def start_server(self) -> None:
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

    async def stop_server(self) -> None:
        try:
            await self.slime.stop_server(self.server.name)
        except SlimeError as error:
            self.slime.notify_error(error)
            return
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
