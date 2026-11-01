"""Textual user interface for Slime."""

from __future__ import annotations

import asyncio
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.widgets import Footer, Header

from ..api.papermc import PaperMCClient
from ..config import Config
from ..errors import SlimeError
from ..java import JavaManager
from ..models import Server
from ..process import ServerProcess, ServerState
from ..provision import Provisioner
from ..store import ServerStore
from .screens.create import CreateServerScreen
from .screens.dashboard import DashboardView
from .screens.doctor import DoctorScreen
from .screens.java import JavaScreen
from .screens.server import ServerScreen


class SlimeApp(App[None]):
    """The Slime TUI."""

    TITLE = "Slime"
    SUB_TITLE = "Minecraft server manager"
    CSS_PATH = "app.tcss"
    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("n", "new_server", "New server"),
        ("j", "java", "Java"),
        ("d", "doctor", "Doctor"),
        ("r", "refresh", "Refresh"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.store = ServerStore(config)
        self.papermc = PaperMCClient(
            config.settings.fill_base_url,
            user_agent=config.settings.user_agent,
            timeout=config.settings.request_timeout,
        )
        self.java_manager = JavaManager(config)
        self.provisioner = Provisioner(
            config, self.store, self.papermc, self.java_manager
        )
        self.processes: dict[str, ServerProcess] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DashboardView()
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_dashboard()
        self.set_interval(3.0, self.refresh_dashboard)

    # --------------------------------------------------------------- dashboard
    def refresh_dashboard(self) -> None:
        try:
            dashboard = self.query_one(DashboardView)
        except NoMatches:
            return
        dashboard.refresh_data()

    def open_server(self, name: str) -> None:
        try:
            server = self.store.get(name)
        except SlimeError as error:
            self.notify_error(error)
            return
        self.push_screen(ServerScreen(self, server))

    def action_new_server(self) -> None:
        self.push_screen(CreateServerScreen(self), self._after_create)

    def _after_create(self, server: Server | None) -> None:
        self.refresh_dashboard()
        if server is not None:
            self.open_server(server.name)

    def action_java(self) -> None:
        self.push_screen(JavaScreen(self))

    def action_doctor(self) -> None:
        self.push_screen(DoctorScreen(self))

    def action_refresh(self) -> None:
        self.refresh_dashboard()
        self.notify("Refreshed.", timeout=2)

    # ---------------------------------------------------------------- processes
    def get_process(self, name: str) -> ServerProcess | None:
        return self.processes.get(name)

    async def start_server(self, server: Server) -> ServerProcess:
        existing = self.processes.get(server.name)
        if existing is not None and existing.is_running:
            return existing

        install = self.java_manager.require_for(server)
        process = ServerProcess(
            server,
            self.store.path(server.name),
            install.path,
            log_dir=self.config.paths.logs,
        )
        def on_state(state: ServerState, name: str = server.name) -> None:
            self._on_process_state(name, state)

        process.add_state_listener(on_state)
        self.processes[server.name] = process
        try:
            await process.start()
        except Exception:
            self.processes.pop(server.name, None)
            raise
        self.refresh_dashboard()
        return process

    async def stop_server(self, name: str) -> None:
        process = self.processes.get(name)
        if process is not None:
            await process.stop()
        self.refresh_dashboard()

    def _on_process_state(self, name: str, state: ServerState) -> None:
        self.refresh_dashboard()
        if state is ServerState.CRASHED:
            self.notify(
                f"Server '{name}' exited unexpectedly. Open its console for details.",
                severity="error",
                timeout=8,
            )
        screen = self.screen
        if isinstance(screen, ServerScreen) and screen.server.name == name:
            screen.on_process_state(state)

    # ------------------------------------------------------------------ errors
    def notify_error(self, error: Exception) -> None:
        message = error.message if isinstance(error, SlimeError) else str(error)
        hint = error.hint if isinstance(error, SlimeError) else None
        self.notify(
            message + (f"\n{hint}" if hint else ""),
            severity="error",
            timeout=8,
        )

    # ------------------------------------------------------------------- quit
    async def action_quit(self) -> None:
        running = [process for process in self.processes.values() if process.is_running]
        if running:
            self.notify(
                f"Stopping {len(running)} running server(s)…",
                severity="warning",
                timeout=5,
            )
            await asyncio.gather(
                *(process.stop(timeout=20) for process in running),
                return_exceptions=True,
            )
        self.exit()

    def on_unmount(self) -> None:
        self.papermc.close()
        self.java_manager.client.close()
        for process in self.processes.values():
            process.terminate_now()


def run_tui(config: Config) -> None:
    """Launch the TUI (blocking)."""
    SlimeApp(config).run()


__all__ = ["SlimeApp", "run_tui"]
