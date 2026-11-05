"""Textual user interface for Slime."""

from __future__ import annotations

import asyncio
import contextlib
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.widgets import Footer, Header

from ..api.catalog import ProjectCatalog
from ..api.papermc import PaperMCClient
from ..api.purpur import PurpurClient
from ..config import Config
from ..errors import ServerError, SlimeError
from ..java import JavaManager
from ..models import Server
from ..process import ServerProcess, ServerState
from ..provision import Provisioner
from ..rcon import RconClient, RconError, require_rcon_config, shutdown_command
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
        self.papermc = ProjectCatalog(
            PaperMCClient(
                config.settings.fill_base_url,
                user_agent=config.settings.user_agent,
                timeout=config.settings.request_timeout,
            ),
            PurpurClient(
                config.settings.purpur_base_url,
                user_agent=config.settings.user_agent,
                timeout=config.settings.request_timeout,
            ),
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

    async def start_server(
        self, server: Server, *, extra_args: list[str] | None = None
    ) -> ServerProcess:
        existing = self.processes.get(server.name)
        if existing is not None and existing.is_running:
            return existing

        running, pid = self.store.is_running(server.name)
        if running and (existing is None or pid != existing.pid):
            raise ServerError(
                f"Server '{server.name}' is already running (pid {pid}).",
                hint=(
                    "It was started by another process. Use Stop to shut it "
                    "down through RCON, or open its original console."
                ),
            )

        install = self.java_manager.require_for(server)
        process = ServerProcess(
            server,
            self.store.path(server.name),
            install.path,
            log_dir=self.config.paths.logs,
            extra_args=extra_args,
            java_home=install.home,
            on_recovery=lambda args: self._remember_recovery(server, args),
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

    def _remember_recovery(self, server: Server, args: list[str]) -> None:
        """Persist arguments suggested by the latest server error."""
        merged = list(dict.fromkeys([*server.recovery_args, *args]))
        if merged == server.recovery_args:
            return
        server.recovery_args = merged
        with contextlib.suppress(SlimeError, OSError):
            self.store.save(server)

    async def stop_server(self, name: str) -> None:
        process = self.processes.get(name)
        if process is not None and process.is_running:
            await process.stop()
        else:
            running, _pid = self.store.is_running(name)
            if running:
                await self.stop_external(name)
        self.refresh_dashboard()

    async def send_remote_command(self, server: Server, command: str) -> str:
        """Send one command to a server running in another process."""
        config = require_rcon_config(self.store.path(server.name))

        def run() -> str:
            with RconClient(config) as client:
                return client.command(command)

        return await asyncio.to_thread(run)

    async def stop_external(self, name: str, timeout: float = 30.0) -> None:
        """Ask a server started by another process to stop through RCON."""
        server = self.store.get(name)
        config = require_rcon_config(self.store.path(name))

        def request_stop() -> None:
            # The server often closes the socket before replying.
            with RconClient(config) as client, contextlib.suppress(RconError):
                client.command(shutdown_command(server))

        await asyncio.to_thread(request_stop)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, timeout)
        while loop.time() < deadline:
            if not self.store.is_running(name)[0]:
                return
            await asyncio.sleep(0.5)
        raise ServerError(
            f"Server '{name}' is still running after {timeout:g}s.",
            hint=(
                "It may be busy saving the world. Wait a little longer, or "
                "stop it from the console where it was started."
            ),
        )

    def _on_process_state(self, name: str, state: ServerState) -> None:
        self.refresh_dashboard()
        if state is ServerState.CRASHED:
            process = self.processes.get(name)
            if process is not None and process.world_reset_suggested:
                with contextlib.suppress(SlimeError, OSError):
                    server = self.store.get(name)
                    if not server.world_reset_suggested:
                        server.world_reset_suggested = True
                        self.store.save(server)
            self.notify(
                f"Server '{name}' exited unexpectedly. Open its console for details.",
                severity="error",
                timeout=8,
            )
        screen = self.screen
        if isinstance(screen, ServerScreen) and screen.server.name == name:
            if state is ServerState.CRASHED:
                process = self.processes.get(name)
                if process is not None and process.world_reset_suggested:
                    screen.server.world_reset_suggested = True
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
    from ..windows_terminal import relaunch_in_windows_terminal

    if relaunch_in_windows_terminal():
        return
    SlimeApp(config).run()


__all__ = ["SlimeApp", "run_tui"]
