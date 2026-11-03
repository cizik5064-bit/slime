"""Dashboard: the server list and primary actions."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, DataTable, Static

from ...models import Server
from ...process import ServerState

if TYPE_CHECKING:
    from ..app import SlimeApp


class DashboardView(Container):
    """Main screen content: one row per configured server."""

    def compose(self) -> ComposeResult:
        yield Static("Your servers", id="dashboard-title")
        yield DataTable(id="servers", cursor_type="row", zebra_stripes=True)
        with Horizontal(id="dashboard-buttons"):
            yield Button("New server", id="new", variant="success")
            yield Button("Open", id="open", variant="primary")
            yield Button("Java", id="java")
            yield Button("Doctor", id="doctor")
            yield Button("Refresh", id="refresh")
            yield Button("Quit", id="quit", variant="error")
        yield Static("", id="dashboard-status")

    def on_mount(self) -> None:
        table = self.query_one("#servers", DataTable)
        table.add_columns(
            "Name",
            "Project",
            "Version",
            "Build",
            "Port",
            "Memory",
            "Java",
            "Status",
        )
        self.refresh_data()

    def refresh_data(self) -> None:
        app = cast("SlimeApp", self.app)
        table = self.query_one("#servers", DataTable)
        table.clear()
        servers: list[Server] = app.store.list()
        self._names = [server.name for server in servers]
        for server in servers:
            process = app.get_process(server.name)
            if process is not None:
                state = process.state
                status = self._state_label(state)
            else:
                running, pid = app.store.is_running(server.name)
                status = (
                    f"[green]running[/green] (pid {pid})"
                    if running
                    else "[dim]stopped[/dim]"
                )
            table.add_row(
                escape(server.name),
                server.project.display_name,
                escape(server.minecraft_version),
                str(server.build),
                str(server.port),
                f"{server.memory_mb} MB",
                str(server.java_major),
                status,
                key=server.name,
            )

        installed = len(app.java_manager.installed())
        if servers:
            summary = (
                f"{len(servers)} server(s) - {installed} Java runtime(s) - "
                f"{app.config.paths.home}"
            )
        else:
            summary = (
                "No servers yet. Press N or click 'New server'. "
                f"Slime home: {app.config.paths.home}"
            )
        self.query_one("#dashboard-status", Static).update(summary)

    @staticmethod
    def _state_label(state: ServerState) -> str:
        color = {
            ServerState.RUNNING: "green",
            ServerState.STARTING: "yellow",
            ServerState.STOPPING: "yellow",
            ServerState.CRASHED: "red",
            ServerState.STOPPED: "dim",
        }[state]
        return f"[{color}]{state.value}[/{color}]"

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value:
            cast("SlimeApp", self.app).open_server(str(event.row_key.value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app = cast("SlimeApp", self.app)
        button_id = event.button.id
        if button_id == "new":
            app.action_new_server()
        elif button_id == "open":
            table = self.query_one("#servers", DataTable)
            row = table.cursor_row
            if isinstance(row, int) and 0 <= row < len(getattr(self, "_names", [])):
                app.open_server(self._names[row])
        elif button_id == "java":
            app.action_java()
        elif button_id == "doctor":
            app.action_doctor()
        elif button_id == "refresh":
            app.action_refresh()
        elif button_id == "quit":
            app.run_worker(app.action_quit())
