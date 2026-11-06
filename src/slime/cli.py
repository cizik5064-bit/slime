"""Command-line interface for Slime."""

from __future__ import annotations

import asyncio
import signal
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, NoReturn, cast

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.prompt import Confirm, Prompt
from rich.table import Table

from . import APP_NAME, PROJECT_URL, __version__
from .api.catalog import ProjectCatalog
from .api.papermc import PaperMCClient
from .api.purpur import PurpurClient
from .backup import BackupInfo, BackupManager
from .checks import CheckResult, CheckStatus, has_failures, run_checks, summarize
from .config import Config, Settings
from .content import ContentManager
from .errors import ContentError, JavaError, ServerError, SlimeError
from .java import JavaManager
from .logging_setup import setup_logging
from .models import (
    PROJECTS,
    ContentHit,
    ContentKind,
    ContentSource,
    ContentVersion,
    JavaInstall,
    Project,
    Server,
    required_java_major,
    validate_memory,
)
from .process import ServerProcess, ServerState
from .properties import write_eula
from .provision import CreateRequest, Provisioner
from .rcon import RconClient, RconError, require_rcon_config, shutdown_command
from .store import ServerStore

console = Console()
error_console = Console(stderr=True)

# ---------------------------------------------------------------------------
# Application context
# ---------------------------------------------------------------------------


class AppContext:
    """Lazily-created services shared by CLI commands."""

    def __init__(self, config: Config, *, verbose: bool = False) -> None:
        self.config = config
        self.verbose = verbose
        self._store: ServerStore | None = None
        self._catalog: ProjectCatalog | None = None
        self._java: JavaManager | None = None
        self._provisioner: Provisioner | None = None
        self._backups: BackupManager | None = None
        self._content: ContentManager | None = None

    @property
    def store(self) -> ServerStore:
        if self._store is None:
            self._store = ServerStore(self.config)
        return self._store

    @property
    def catalog(self) -> ProjectCatalog:
        if self._catalog is None:
            settings = self.config.settings
            self._catalog = ProjectCatalog(
                PaperMCClient(
                    settings.fill_base_url,
                    user_agent=settings.user_agent,
                    timeout=settings.request_timeout,
                ),
                PurpurClient(
                    settings.purpur_base_url,
                    user_agent=settings.user_agent,
                    timeout=settings.request_timeout,
                ),
            )
        return self._catalog

    @property
    def java_manager(self) -> JavaManager:
        if self._java is None:
            self._java = JavaManager(self.config)
        return self._java

    @property
    def provisioner(self) -> Provisioner:
        if self._provisioner is None:
            self._provisioner = Provisioner(
                self.config, self.store, self.catalog, self.java_manager
            )
        return self._provisioner

    @property
    def backups(self) -> BackupManager:
        if self._backups is None:
            self._backups = BackupManager(self.config, self.store)
        return self._backups

    @property
    def content(self) -> ContentManager:
        if self._content is None:
            self._content = ContentManager(self.config, self.store)
        return self._content


def _ctx(context: typer.Context) -> AppContext:
    return cast(AppContext, context.obj)


def _fail(error: SlimeError) -> NoReturn:
    error_console.print(f"[bold red]Error:[/bold red] {escape(error.message)}")
    if error.hint:
        error_console.print(f"[yellow]Hint:[/yellow] {escape(error.hint)}")
    raise typer.Exit(1)


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except SlimeError as error:
        _fail(error)


# ---------------------------------------------------------------------------
# Root app
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"{APP_NAME} {__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="slime",
    help=(
        "[bold green]Slime[/bold green] - a friendly Minecraft server manager.\n\n"
        "Run [cyan]slime[/cyan] with no arguments to open the TUI."
    ),
    no_args_is_help=False,
    invoke_without_command=True,
    add_completion=True,
    rich_markup_mode="rich",
    epilog=f"Documentation: {PROJECT_URL}",
)

server_app = typer.Typer(
    help="Create, inspect and run Minecraft servers.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
java_app = typer.Typer(
    help="Install and inspect Eclipse Temurin (Adoptium) JDKs.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
config_app = typer.Typer(
    help="Show or change Slime settings.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
backup_app = typer.Typer(
    help="Create, restore and delete compressed server backups.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
content_app = typer.Typer(
    help="Search, install and remove plugins or mods (Modrinth and Hangar).",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(server_app, name="server")
app.add_typer(java_app, name="java")
app.add_typer(config_app, name="config")
app.add_typer(backup_app, name="backup")
app.add_typer(content_app, name="content")


@app.callback()
def _root(
    context: typer.Context,
    home: Annotated[
        Path | None,
        typer.Option(
            "--home",
            help="Slime home directory (default: ~/.slime).",
            envvar="SLIME_HOME",
            show_default=False,
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging."),
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Show the Slime version and exit.",
        ),
    ] = False,
) -> None:
    if context.invoked_subcommand is None:
        if sys.stdout.isatty():
            from .tui.app import run_tui

            run_tui(Config(home))
            raise typer.Exit()
        console.print(context.get_help())
        raise typer.Exit()

    with _errors():
        config = Config(home)
    setup_logging(config.paths, verbose=verbose)
    context.obj = AppContext(config, verbose=verbose)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status_text(status: CheckStatus) -> str:
    color = {
        CheckStatus.OK: "green",
        CheckStatus.INFO: "cyan",
        CheckStatus.WARN: "yellow",
        CheckStatus.FAIL: "red",
    }[status]
    return f"[{color}]{status.value.upper()}[/{color}]"


def _print_checks(results: list[CheckResult]) -> None:
    table = Table(title="Environment check", header_style="bold")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Details")
    table.add_column("Hint", style="dim")
    for result in results:
        table.add_row(
            escape(result.title),
            _status_text(result.status),
            escape(result.message),
            escape(result.hint or ""),
        )
    console.print(table)
    counts = summarize(results)
    console.print(
        f"[green]{counts[CheckStatus.OK]} ok[/green]  "
        f"[cyan]{counts[CheckStatus.INFO]} info[/cyan]  "
        f"[yellow]{counts[CheckStatus.WARN]} warning(s)[/yellow]  "
        f"[red]{counts[CheckStatus.FAIL]} error(s)[/red]"
    )


def _print_server_table(servers: list[Server], store: ServerStore) -> None:
    table = Table(title="Servers", header_style="bold")
    table.add_column("Name", style="bold")
    table.add_column("Project")
    table.add_column("Version")
    table.add_column("Build", justify="right")
    table.add_column("Port", justify="right")
    table.add_column("Memory", justify="right")
    table.add_column("Java", justify="right")
    table.add_column("Status")
    for server in servers:
        running, pid = store.is_running(server.name)
        status = f"[green]running[/green] (pid {pid})" if running else "[dim]stopped[/dim]"
        table.add_row(
            escape(server.name),
            server.project.display_name,
            escape(server.minecraft_version),
            str(server.build),
            str(server.port),
            f"{server.memory_mb} MB",
            str(server.java_major),
            status,
        )
    console.print(table)


def _memory_label(server: Server) -> str:
    minimum = server.min_memory_mb or server.memory_mb
    if minimum == server.memory_mb:
        return f"{server.memory_mb} MB"
    return f"{minimum}-{server.memory_mb} MB"


def _server_payload(server: Server, store: ServerStore) -> dict[str, object]:
    running, pid = store.is_running(server.name)
    payload = server.to_dict()
    payload["running"] = running
    payload["pid"] = pid
    payload["path"] = str(store.path(server.name))
    return payload


def _java_payload(install: JavaInstall) -> dict[str, object]:
    return install.to_dict()


def _prompt_project() -> Project:
    table = Table(title="Choose a project", show_header=False, box=None)
    table.add_column("Option", style="bold cyan")
    table.add_column("Project")
    table.add_column("Kind")
    for index, project in enumerate(PROJECTS, start=1):
        table.add_row(str(index), project.display_name, project.kind)
    console.print(table)
    answer = Prompt.ask(
        "Project",
        choices=[project.value for project in PROJECTS],
        default=Project.PAPER.value,
    )
    return Project.parse(answer)


def _prompt_version(context: AppContext, project: Project) -> str:
    try:
        versions = context.catalog.versions(project.value)
    except SlimeError:
        return Prompt.ask("Minecraft version (or 'latest')", default="latest")
    table = Table(title=f"{project.display_name} versions", show_header=False, box=None)
    table.add_column("Version", style="cyan")
    table.add_column("Version", style="cyan")
    table.add_column("Version", style="cyan")
    latest = versions[:18]
    rows = [latest[index : index + 3] for index in range(0, len(latest), 3)]
    for row in rows:
        table.add_row(*row)
    console.print(table)
    answer = Prompt.ask(
        "Minecraft version (or 'latest')",
        default=versions[0] if versions else "latest",
    ).strip()
    return "" if answer.lower() in {"", "latest"} else answer


def _confirm_eula(*, default: bool = False) -> bool:
    console.print(
        Panel(
            "Minecraft servers require you to accept the Minecraft End User "
            "License Agreement.\n\nRead it here: [link=https://aka.ms/MinecraftEULA]"
            "https://aka.ms/MinecraftEULA[/link]\n\n"
            "Slime only writes [bold]eula=true[/bold] if you explicitly agree.",
            title="Minecraft EULA",
            border_style="yellow",
        )
    )
    return Confirm.ask("Do you accept the Minecraft EULA?", default=default)


# ---------------------------------------------------------------------------
# TUI
# ---------------------------------------------------------------------------


@app.command("tui")
def tui_command(context: typer.Context) -> None:
    """Open the full-screen terminal interface."""
    from .tui.app import run_tui

    run_tui(_ctx(context).config)


@app.command("doctor", rich_help_panel="Diagnostics")
def doctor_command(
    context: typer.Context,
    server: Annotated[
        str | None,
        typer.Option("--server", "-s", help="Check one server instead of the whole setup."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Check Python, OS, disk, Java, ports, EULA and server files."""
    app_context = _ctx(context)
    with _errors():
        target = app_context.store.get(server) if server else None
        results = run_checks(
            app_context.config,
            app_context.store,
            app_context.java_manager,
            server=target,
        )

    if as_json:
        console.print_json(
            data=[
                {
                    "id": result.id,
                    "title": result.title,
                    "status": result.status.value,
                    "message": result.message,
                    "hint": result.hint,
                    "scope": result.scope,
                }
                for result in results
            ]
        )
    else:
        _print_checks(results)

    if has_failures(results):
        raise typer.Exit(2)


# ---------------------------------------------------------------------------
# Server commands
# ---------------------------------------------------------------------------


@server_app.command("list")
def server_list(
    context: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """List configured servers."""
    app_context = _ctx(context)
    with _errors():
        servers = app_context.store.list()

    if as_json:
        console.print_json(
            data=[_server_payload(server, app_context.store) for server in servers]
        )
        return
    if not servers:
        console.print("[dim]No servers yet.[/dim]")
        console.print("Create one with: [cyan]slime server create my-server[/cyan]")
        return
    _print_server_table(servers, app_context.store)


@server_app.command("create")
def server_create(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name, also used as the directory name.")],
    project: Annotated[
        str | None,
        typer.Option("--project", "-p", help="paper, folia, purpur, velocity or waterfall."),
    ] = None,
    version: Annotated[
        str | None,
        typer.Option("--version", help="Minecraft version (default: latest)."),
    ] = None,
    build: Annotated[
        int | None,
        typer.Option("--build", "-b", help="Exact build number (default: latest)."),
    ] = None,
    channel: Annotated[
        str,
        typer.Option("--channel", help="Build channel: STABLE, BETA, ALPHA or ANY."),
    ] = "STABLE",
    memory: Annotated[
        int | None,
        typer.Option("--memory", "-m", help="Memory limit in MB (default from config)."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Server port (default from config)."),
    ] = None,
    java: Annotated[
        int | None,
        typer.Option("--java", help="Java major version (default: required by the project)."),
    ] = None,
    accept_eula: Annotated[
        bool,
        typer.Option(
            "--accept-eula",
            help="Accept https://aka.ms/MinecraftEULA and write eula=true.",
        ),
    ] = False,
    motd: Annotated[
        str | None,
        typer.Option("--motd", help="Message of the day written to server.properties."),
    ] = None,
) -> None:
    """Download a server build and create a new server directory."""
    app_context = _ctx(context)
    interactive = sys.stdin.isatty()

    with _errors():
        if project is None:
            if not interactive:
                raise ServerError(
                    "Missing --project.",
                    hint="Supported projects: " + ", ".join(p.value for p in PROJECTS),
                )
            project_obj = _prompt_project()
        else:
            project_obj = Project.parse(project)

        channel = channel.strip().upper()
        if channel not in {"STABLE", "BETA", "ALPHA", "ANY"}:
            raise ServerError(
                f"Invalid channel '{channel}'.",
                hint="Use STABLE, BETA, ALPHA or ANY.",
            )

        if version is None:
            version = _prompt_version(app_context, project_obj) if interactive else ""
        version = version.strip()

        accepted = accept_eula
        if not project_obj.is_proxy and not accepted:
            if interactive:
                accepted = _confirm_eula()
            else:
                console.print(
                    "[yellow]EULA not accepted.[/yellow] The server will not start until "
                    f"you run: [cyan]slime server eula {name} --accept[/cyan]"
                )

        request = CreateRequest(
            name=name,
            project=project_obj,
            version=version,
            build=build,
            channel=channel,
            memory_mb=memory,
            port=port,
            java_major=java,
            accept_eula=accepted,
            motd=motd,
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Preparing…", total=None)

            def on_progress(stage: str, done: int, total: int | None) -> None:
                progress.update(task, description=stage, completed=done, total=total)

            server = app_context.provisioner.create(request, progress=on_progress)

    console.print(
        Panel(
            f"[bold green]Server created[/bold green]\n\n"
            f"Name:     [cyan]{escape(server.name)}[/cyan]\n"
            f"Project:  {server.project.display_name} {escape(server.minecraft_version)} "
            f"(build {server.build})\n"
            f"Memory:   {_memory_label(server)}\n"
            f"Port:     {server.port}\n"
            f"Java:     {server.java_major}\n"
            f"Location: {escape(str(app_context.store.path(server.name)))}",
            title=APP_NAME,
            border_style="green",
        )
    )
    console.print(
        "Next steps:\n"
        f"  1. [cyan]slime java install {server.java_major}[/cyan]\n"
        f"  2. [cyan]slime server run {server.name}[/cyan]\n"
        "  or open the TUI: [cyan]slime[/cyan]"
    )
    if not server.is_proxy and not server.eula_accepted:
        console.print(
            f"[yellow]Remember:[/yellow] run [cyan]slime server eula {server.name} --accept[/cyan] "
            "after reading the EULA."
        )


@server_app.command("info")
def server_info(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name.")],
    checks: Annotated[
        bool, typer.Option("--checks", help="Also run environment checks for this server.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Show details for one server."""
    app_context = _ctx(context)
    with _errors():
        server = app_context.store.get(name)
        running, pid = app_context.store.is_running(name)
        java_install = app_context.java_manager.find_for(server)
        results = (
            run_checks(
                app_context.config,
                app_context.store,
                app_context.java_manager,
                server=server,
            )
            if checks
            else None
        )

    if as_json:
        payload = _server_payload(server, app_context.store)
        payload["java"] = _java_payload(java_install) if java_install else None
        if results is not None:
            payload["checks"] = [
                {
                    "id": result.id,
                    "status": result.status.value,
                    "message": result.message,
                    "hint": result.hint,
                }
                for result in results
            ]
        console.print_json(data=payload)
        return

    table = Table(title=f"Server: {server.name}", show_header=False, box=None)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Project", f"{server.project.display_name} ({server.kind})")
    table.add_row("Minecraft", server.minecraft_version)
    table.add_row("Build", str(server.build))
    table.add_row("Status", f"running (pid {pid})" if running else "stopped")
    table.add_row("Path", str(app_context.store.path(server.name)))
    table.add_row("Jar", server.jar_file)
    table.add_row("Port", str(server.port))
    table.add_row("Memory", _memory_label(server))
    if server.cpu_cores is not None:
        table.add_row("CPU cores", str(server.cpu_cores))
    table.add_row("Java required", str(server.java_major))
    table.add_row(
        "Java resolved",
        str(java_install.path) if java_install else "[red]not installed[/red]",
    )
    table.add_row("EULA", "accepted" if server.eula_accepted else "not accepted")
    table.add_row("Created", server.created_at)
    console.print(table)
    if results is not None:
        _print_checks(results)


@server_app.command("run")
def server_run(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name.")],
    memory: Annotated[
        int | None,
        typer.Option("--memory", "-m", help="Override memory for this run (MB)."),
    ] = None,
    java: Annotated[
        Path | None,
        typer.Option("--java", help="Override the Java executable for this run."),
    ] = None,
    no_console: Annotated[
        bool,
        typer.Option("--no-console", help="Do not read commands from stdin."),
    ] = False,
) -> None:
    """Start a server in the foreground and attach the console.

    Press Ctrl+C or type ``stop`` to shut it down gracefully.
    """
    app_context = _ctx(context)
    recovery_args: list[str] = []
    with _errors():
        server = app_context.store.get(name)
        running, pid = app_context.store.is_running(name)
        if running:
            raise ServerError(
                f"Server '{name}' is already running (pid {pid}).",
                hint=(
                    "Stop it with `slime server stop " + name + "`, from the "
                    "TUI, or from the console where it was started."
                ),
            )
        if memory is not None:
            server.memory_mb = validate_memory(memory)
        if java is not None:
            install = app_context.java_manager.inspect(java)
            if install is None:
                raise JavaError(f"{java} is not a working Java executable.")
            if install.major != server.java_major:
                raise JavaError(
                    f"{java} is Java {install.major}, but this server requires Java "
                    f"{server.java_major}."
                )
            server.java_path = str(install.path)
        java_install = app_context.java_manager.require_for(server)

        if not server.is_proxy and not server.eula_accepted:
            if sys.stdin.isatty() and _confirm_eula():
                write_eula(app_context.store.path(name) / "eula.txt", True)
                server.eula_accepted = True
                app_context.store.save(server)
            else:
                raise ServerError(
                    "The Minecraft EULA has not been accepted.",
                    hint=f"Read https://aka.ms/MinecraftEULA, then run: "
                    f"slime server eula {name} --accept",
                )

        jar = app_context.store.path(name) / server.jar_file
        if not jar.is_file():
            raise ServerError(
                f"Server jar is missing: {jar}",
                hint="Recreate the server or download the jar manually.",
            )
        if server.world_reset_suggested:
            console.print(
                "[yellow]Warning:[/yellow] the previous crash suggests a damaged "
                "world. Open the TUI and use Edit -> Dangerous -> Reset world if "
                "the server keeps failing."
            )
        recovery_args = _offer_recovery_args(server, app_context.store)
        server_dir = app_context.store.path(name)

    code = asyncio.run(
        _run_foreground(
            app_context,
            server,
            java_install,
            server_dir=server_dir,
            no_console=no_console,
            extra_args=(
                [*server.extra_args, *recovery_args] if recovery_args else None
            ),
        )
    )
    if code != 0:
        raise typer.Exit(code)


def _offer_recovery_args(server: Server, store: ServerStore) -> list[str]:
    """Offer recovery flags and return them for this launch only."""
    if not server.recovery_args:
        return []
    flags = " ".join(server.recovery_args)
    if not sys.stdin.isatty():
        console.print(
            f"[yellow]Hint:[/yellow] the previous run suggested {flags}. "
            "Start Slime interactively to accept it."
        )
        return []
    accept = Confirm.ask(
        f"The previous run suggested starting with {flags}. Start with it?",
        default=True,
    )
    transient = list(server.recovery_args) if accept else []
    server.recovery_args = []
    store.save(server)
    return transient


def _remember_recovery(store: ServerStore, server: Server, args: list[str]) -> None:
    """Persist recovery arguments detected in server output."""
    merged = list(dict.fromkeys([*server.recovery_args, *args]))
    if merged == server.recovery_args:
        return
    server.recovery_args = merged
    with suppress(ServerError, OSError):
        store.save(server)


async def _run_foreground(
    app_context: AppContext,
    server: Server,
    java_install: JavaInstall,
    *,
    server_dir: Path,
    no_console: bool,
    extra_args: list[str] | None = None,
) -> int:
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def handle_sigint(*_: object) -> None:
        loop.call_soon_threadsafe(stop_event.set)

    previous_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, handle_sigint)

    process = ServerProcess(
        server,
        server_dir,
        java_install.path,
        log_dir=app_context.config.paths.logs,
        extra_args=extra_args,
        java_home=java_install.home,
        on_recovery=lambda args: _remember_recovery(app_context.store, server, args),
    )
    process.add_line_listener(
        lambda line: console.print(line, markup=False, highlight=False, soft_wrap=True)
    )

    def on_state(state: ServerState) -> None:
        if state is ServerState.RUNNING:
            console.print("[green]Server is ready.[/green]")
        elif state is ServerState.CRASHED:
            console.print("[red]Server exited unexpectedly.[/red]")

    process.add_state_listener(on_state)

    try:
        await process.start()
        console.print(
            f"[green]Started[/green] {server.name} (pid {process.pid}). "
            "Press [bold]Ctrl+C[/bold] to stop."
        )
        if not no_console and sys.stdin.isatty():
            console.print("[dim]Type a command and press Enter; 'stop' shuts it down.[/dim]")
            threading.Thread(
                target=_console_thread,
                args=(loop, process),
                daemon=True,
                name="slime-console-input",
            ).start()

        wait_task = asyncio.create_task(process.wait())
        stop_task = asyncio.create_task(stop_event.wait())
        _done, pending = await asyncio.wait(
            {wait_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if process.is_running:
            console.print("[yellow]Stopping server…[/yellow]")
            await process.stop()
        code = process.exit_code
        if process.state is ServerState.CRASHED and not code:
            return 1
        return code if code is not None else 0
    finally:
        if process.is_running:
            await process.stop()
        signal.signal(signal.SIGINT, previous_handler)


def _console_thread(loop: asyncio.AbstractEventLoop, process: ServerProcess) -> None:
    while process.is_running:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not line:
            continue
        if line.lower() in {"exit", "quit"}:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(process.send(line), loop)
            future.result(timeout=15)
        except Exception as exc:
            console.print(f"[red]Command failed:[/red] {escape(str(exc))}")


@server_app.command("eula")
def server_eula(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name.")],
    accept: Annotated[
        bool | None,
        typer.Option(
            "--accept/--revoke",
            help="Accept or revoke the Minecraft EULA. Without a flag Slime asks.",
        ),
    ] = None,
) -> None:
    """Accept (or revoke) the Minecraft EULA for a server."""
    app_context = _ctx(context)
    with _errors():
        server = app_context.store.get(name)
        if server.is_proxy:
            console.print(
                f"[cyan]{server.project.display_name}[/cyan] is a proxy and does not "
                "require eula.txt."
            )
            return
        if accept is None:
            if not sys.stdin.isatty():
                raise ServerError(
                    "Refusing to change the EULA state without an explicit choice.",
                    hint=f"Pass --accept or --revoke, for example: "
                    f"slime server eula {name} --accept",
                )
            accepted = Confirm.ask(
                "Do you accept the Minecraft EULA at https://aka.ms/MinecraftEULA?",
                default=False,
            )
            accept = bool(accepted)
            if not accept and not Confirm.ask(
                f"Revoke the EULA for '{name}'?", default=False
            ):
                console.print("Cancelled.")
                raise typer.Exit()
        write_eula(app_context.store.path(name) / "eula.txt", accepted=accept)
        server.eula_accepted = accept
        app_context.store.save(server)

    if accept:
        console.print(
            f"[green]EULA accepted[/green] for '{name}'. "
            "You confirmed https://aka.ms/MinecraftEULA."
        )
    else:
        console.print(f"[yellow]EULA revoked[/yellow] for '{name}'.")


@server_app.command("delete")
def server_delete(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    keep_files: Annotated[
        bool,
        typer.Option("--keep-files", help="Unregister the server but keep its directory."),
    ] = False,
) -> None:
    """Delete a server and its world files."""
    app_context = _ctx(context)
    with _errors():
        server = app_context.store.get(name)
        running, pid = app_context.store.is_running(name)
        if running:
            raise ServerError(
                f"Server '{name}' is running (pid {pid}).",
                hint="Stop it first, then delete it.",
            )
        if not yes:
            if not sys.stdin.isatty():
                raise ServerError(
                    "Refusing to delete without confirmation.",
                    hint="Pass --yes to delete non-interactively.",
                )
            action = "Unregister" if keep_files else "Delete"
            if not Confirm.ask(
                f"{action} '{server.name}' and all its files?", default=False
            ):
                console.print("Cancelled.")
                raise typer.Exit()
        path = app_context.store.path(name)
        app_context.store.delete(name, keep_files=keep_files)
    if keep_files:
        console.print(f"[green]Unregistered[/green] '{name}'. Files kept at {escape(str(path))}.")
    else:
        console.print(f"[green]Deleted[/green] '{name}' and {escape(str(path))}.")


@server_app.command("path")
def server_path(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name.")],
) -> None:
    """Print the server directory (useful in scripts)."""
    app_context = _ctx(context)
    with _errors():
        app_context.store.get(name)
    console.print(str(app_context.store.path(name)))


@server_app.command("cmd")
def server_cmd(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name.")],
    command: Annotated[
        list[str],
        typer.Argument(help="Command and its arguments, e.g. say hello."),
    ],
) -> None:
    """Send one command to any running server through RCON.

    This works across processes: the server may have been started by the TUI,
    by another ``slime server run``, or by a compatible launcher.
    """
    text = " ".join(command).strip()
    if not text:
        raise typer.BadParameter("A command is required.")
    app_context = _ctx(context)
    with _errors():
        app_context.store.get(name)
        rcon = require_rcon_config(app_context.store.path(name))
        with RconClient(rcon) as client:
            output = client.command(text)
    if output:
        console.print(output, markup=False, highlight=False, soft_wrap=True)
    else:
        console.print("[dim]No response.[/dim]")


@server_app.command("console")
def server_console(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name.")],
) -> None:
    """Attach an interactive RCON console to a running server."""
    app_context = _ctx(context)
    with _errors():
        server = app_context.store.get(name)
        rcon = require_rcon_config(app_context.store.path(name))
        with RconClient(rcon) as client:
            console.print(
                f"Connected to [bold]{escape(server.name)}[/bold] at "
                f"[cyan]{rcon.address}[/cyan]. Type [bold]exit[/bold] to leave."
            )
            while True:
                try:
                    line = input(f"{server.name}> ")
                except (EOFError, KeyboardInterrupt):
                    console.print()
                    break
                command = line.strip()
                if not command:
                    continue
                if command.lower() in {"exit", "quit"}:
                    break
                try:
                    output = client.command(command)
                except RconError as error:
                    _fail(error)
                if output:
                    console.print(output, markup=False, highlight=False, soft_wrap=True)


@server_app.command("stop")
def server_stop(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name.")],
    timeout: Annotated[
        float,
        typer.Option("--timeout", "-t", help="Seconds to wait for the server to exit."),
    ] = 30.0,
) -> None:
    """Stop any running server through RCON (works across processes)."""
    app_context = _ctx(context)
    with _errors():
        server = app_context.store.get(name)
        rcon = require_rcon_config(app_context.store.path(name))
        running, pid = app_context.store.is_running(name)
        with RconClient(rcon) as client, suppress(RconError):
            # A server may close the socket before replying to the shutdown
            # command, which is expected and not an error.
            client.command(shutdown_command(server))
        console.print(f"[green]Stop requested[/green] for '{escape(name)}'.")
        if not running or pid is None:
            console.print(
                "[dim]No PID file was found, so Slime cannot wait for the "
                "process to exit.[/dim]"
            )
            return
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            if not app_context.store.is_running(name)[0]:
                console.print(f"[green]Server '{escape(name)}' stopped.[/green]")
                return
            time.sleep(0.5)
        raise ServerError(
            f"Server '{name}' is still running after {timeout:g}s.",
            hint=(
                "It may be busy saving the world. Wait a little longer, or "
                "stop it from the console where it was started."
            ),
        )


@server_app.command("versions")
def server_versions(
    context: typer.Context,
    project: Annotated[
        str, typer.Option("--project", "-p", help="paper, folia, purpur, velocity or waterfall.")
    ] = "paper",
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum versions to show.")] = 30,
    as_json: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """List Minecraft versions available from the PaperMC Fill API."""
    app_context = _ctx(context)
    with _errors():
        project_obj = Project.parse(project)
        versions = app_context.catalog.versions(project_obj.value)
    if as_json:
        console.print_json(data=versions[: max(1, limit)])
        return
    table = Table(title=f"{project_obj.display_name} versions", header_style="bold")
    table.add_column("Version", style="cyan")
    table.add_column("Java", justify="right")
    for version in versions[: max(1, limit)]:
        table.add_row(version, str(required_java_major(project_obj, version)))
    console.print(table)
    if len(versions) > limit:
        console.print(f"[dim]{len(versions) - limit} more; use --limit to show them.[/dim]")


@server_app.command("builds")
def server_builds(
    context: typer.Context,
    version: Annotated[str, typer.Argument(help="Minecraft version.")],
    project: Annotated[
        str, typer.Option("--project", "-p", help="paper, folia, purpur, velocity or waterfall.")
    ] = "paper",
    channel: Annotated[
        str | None, typer.Option("--channel", help="Filter by STABLE, BETA or ALPHA.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum builds to show.")] = 20,
    as_json: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """List builds for a project and Minecraft version."""
    app_context = _ctx(context)
    with _errors():
        project_obj = Project.parse(project)
        builds = app_context.catalog.builds(project_obj.value, version)
    if channel:
        builds = [build for build in builds if build.channel == channel.upper()]
    builds = builds[-max(1, limit) :]
    builds.reverse()
    if as_json:
        console.print_json(
            data=[
                {
                    "build": build.build,
                    "channel": build.channel,
                    "time": build.time,
                    "downloads": {
                        key: asdict(download) for key, download in build.downloads.items()
                    },
                }
                for build in builds
            ]
        )
        return
    table = Table(title=f"{project_obj.display_name} {version} builds", header_style="bold")
    table.add_column("Build", justify="right")
    table.add_column("Channel")
    table.add_column("Time")
    table.add_column("File")
    table.add_column("Size", justify="right")
    for build in builds:
        try:
            download = build.server_download
        except SlimeError:
            continue
        size = f"{download.size / (1024 * 1024):.1f} MiB" if download.size else "?"
        table.add_row(
            str(build.build),
            build.channel,
            build.time or "",
            escape(download.name),
            size,
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Backup commands
# ---------------------------------------------------------------------------


def _print_backup_table(backups: list[BackupInfo], *, show_server: bool = False) -> None:
    table = Table(title="Backups", header_style="bold")
    if show_server:
        table.add_column("Server", style="bold")
    table.add_column("Backup", style="bold cyan")
    table.add_column("Created (UTC)")
    table.add_column("Size", justify="right")
    table.add_column("Version")
    table.add_column("Files", justify="right")
    table.add_column("Note")
    for info in backups:
        row = [info.identifier, info.created_label, info.size_label]
        if show_server:
            row.insert(0, info.server)
        table.add_row(
            *row,
            escape(info.minecraft_version or "-"),
            str(info.files or "-"),
            escape(info.note),
        )
    console.print(table)


@backup_app.command("create")
def backup_create(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name.")],
    note: Annotated[
        str,
        typer.Option("--note", "-n", help="Optional note stored with the backup."),
    ] = "",
) -> None:
    """Create a maximally compressed .7z backup of a stopped server."""
    app_context = _ctx(context)
    with _errors():
        server = app_context.store.get(name)
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total} files"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Compressing…", total=None)

            def on_progress(relative: str, done: int, total: int) -> None:
                progress.update(
                    task,
                    description=f"Compressing {relative}",
                    completed=done,
                    total=total,
                )

            info = app_context.backups.create(server, note=note, progress=on_progress)

    note_line = f"Note:    {escape(info.note)}\n" if info.note else ""
    console.print(
        Panel(
            f"[bold green]Backup created[/bold green]\n\n"
            f"Name:    [cyan]{escape(info.identifier)}[/cyan]\n"
            f"Server:  {escape(info.server)}\n"
            f"Size:    {info.size_label} ({info.files} files)\n"
            f"{note_line}"
            f"Archive: {escape(str(info.path))}",
            title="Backup",
            border_style="green",
        )
    )


@backup_app.command("list")
def backup_list(
    context: typer.Context,
    name: Annotated[
        str | None,
        typer.Argument(help="Server name (default: all servers)."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """List available backups, newest first."""
    app_context = _ctx(context)
    with _errors():
        if name is not None:
            app_context.store.get(name)
            backups = app_context.backups.list(name)
        else:
            backups = app_context.backups.list_all()

    if as_json:
        console.print_json(data=[info.to_dict() for info in backups])
        return
    if not backups:
        console.print("[dim]No backups yet.[/dim]")
        if name is not None:
            console.print(f"Create one with: [cyan]slime backup create {name}[/cyan]")
        return
    _print_backup_table(backups, show_server=name is None)


@backup_app.command("delete")
def backup_delete(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name.")],
    backup: Annotated[str, typer.Argument(help="Backup id or file name.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
) -> None:
    """Delete one backup archive."""
    app_context = _ctx(context)
    with _errors():
        app_context.store.get(name)
        info = app_context.backups.resolve(name, backup)
        if not yes:
            if not sys.stdin.isatty():
                raise ServerError(
                    "Refusing to delete a backup without confirmation.",
                    hint="Pass --yes to delete non-interactively.",
                )
            if not Confirm.ask(
                f"Delete backup {info.identifier} ({info.size_label})?", default=False
            ):
                console.print("Cancelled.")
                raise typer.Exit()
        app_context.backups.delete(name, info.identifier)
    console.print(f"[green]Deleted[/green] backup {escape(info.identifier)}.")


@backup_app.command("restore")
def backup_restore(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name.")],
    backup: Annotated[str, typer.Argument(help="Backup id or file name.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
) -> None:
    """Restore a backup into a stopped server."""
    app_context = _ctx(context)
    with _errors():
        server = app_context.store.get(name)
        info = app_context.backups.resolve(name, backup)
        if not yes:
            if not sys.stdin.isatty():
                raise ServerError(
                    "Refusing to restore without confirmation.",
                    hint="Pass --yes to restore non-interactively.",
                )
            if not Confirm.ask(
                f"Restore backup {info.identifier} into '{server.name}'?\n"
                "Worlds, plugins and configs from the backup will replace the "
                "current ones. This cannot be undone.",
                default=False,
            ):
                console.print("Cancelled.")
                raise typer.Exit()
        restored = app_context.backups.restore(server, info.identifier)
    console.print(
        f"[green]Restored[/green] {restored} file(s) from {escape(info.identifier)} "
        f"into '{escape(server.name)}'."
    )
    console.print("Start the server when you are ready: " + f"[cyan]slime server run {server.name}[/cyan]")


@backup_app.command("path")
def backup_path(
    context: typer.Context,
    name: Annotated[
        str | None,
        typer.Argument(help="Server name (default: the backups root)."),
    ] = None,
) -> None:
    """Print the backup directory (useful in scripts)."""
    app_context = _ctx(context)
    with _errors():
        if name is not None:
            app_context.store.get(name)
            console.print(str(app_context.backups.directory(name)))
        else:
            console.print(str(app_context.backups.root))


# ---------------------------------------------------------------------------
# Content (plugins and mods)
# ---------------------------------------------------------------------------


def _print_content_table(hits: list[ContentHit]) -> None:
    table = Table(title="Search results", header_style="bold")
    table.add_column("Name", style="bold")
    table.add_column("Source")
    table.add_column("Author")
    table.add_column("Downloads", justify="right")
    table.add_column("Kind")
    table.add_column("Slug")
    for hit in hits:
        table.add_row(
            escape(hit.name),
            hit.source.value,
            escape(hit.author or "-"),
            f"{hit.downloads:,}",
            hit.kind.value,
            escape(hit.slug),
        )
    console.print(table)


@content_app.command("search")
def content_search(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name.")],
    query: Annotated[str, typer.Argument(help="Search phrase.")],
    source: Annotated[
        ContentSource | None,
        typer.Option("--source", help="Limit results to one service."),
    ] = None,
    kind: Annotated[
        ContentKind | None,
        typer.Option("--kind", help="Search plugins or mods."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", min=1, max=100, help="Maximum results."),
    ] = 20,
) -> None:
    """Search content compatible with the server's version and loader."""
    app_context = _ctx(context)
    with _errors():
        server = app_context.store.get(name)
        hits = app_context.content.search(
            server, query, source=source, kind=kind, limit=limit
        )
    if not hits:
        console.print("[dim]No compatible content found.[/dim]")
        return
    _print_content_table(hits)


@content_app.command("install")
def content_install(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name.")],
    project: Annotated[str, typer.Argument(help="Project slug, id or search phrase.")],
    source: Annotated[
        ContentSource | None,
        typer.Option("--source", help="Limit the lookup to one service."),
    ] = None,
    kind: Annotated[
        ContentKind | None,
        typer.Option("--kind", help="Install a plugin or a mod."),
    ] = None,
    version: Annotated[
        str | None,
        typer.Option("--version", "-v", help="Version id or number (default: latest)."),
    ] = None,
    no_deps: Annotated[
        bool,
        typer.Option("--no-deps", help="Do not install required dependencies."),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Replace an already installed version."),
    ] = False,
) -> None:
    """Install a plugin or mod plus its required dependencies."""
    app_context = _ctx(context)
    with _errors():
        server = app_context.store.get(name)
        if app_context.store.is_running(name)[0]:
            raise ServerError(
                f"Cannot install content while '{name}' is running.",
                hint="Stop the server first so the jar can be replaced safely.",
            )
        manager = app_context.content
        hit = manager.find(server, project, source=source, kind=kind)
        content_kind = kind or hit.kind
        if version:
            versions = manager.versions(server, hit, kind=content_kind)
            matches = [
                candidate
                for candidate in versions
                if version in {candidate.version_id, candidate.version_number}
            ]
            if not matches:
                raise ContentError(
                    f"Version '{version}' of {hit.name} is not compatible.",
                    hint="Run `slime content search` to see the project, then "
                    "pick a version id from its page.",
                )
            chosen: ContentVersion = matches[0]
        else:
            chosen = manager.latest_version(server, hit, kind=content_kind)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(
                f"Installing {chosen.filename}", total=None
            )

            def on_progress(done: int, total: int | None) -> None:
                progress.update(task, completed=done, total=total)

            result = manager.install(
                server,
                chosen,
                kind=content_kind,
                with_dependencies=not no_deps,
                overwrite=overwrite,
                progress=on_progress,
            )

    for item in result.installed:
        console.print(
            f"[green]Installed[/green] {escape(item.name)} "
            f"({escape(item.filename)}) into {escape(item.kind.directory)}/"
        )
    for message in result.skipped:
        console.print(f"[yellow]Skipped[/yellow] {escape(message)}")
    for message in result.warnings:
        console.print(f"[yellow]Warning[/yellow] {escape(message)}")
    if not result.installed and not result.skipped:
        console.print("[dim]Nothing was installed.[/dim]")


@content_app.command("list")
def content_list(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name.")],
    as_json: Annotated[
        bool, typer.Option("--json", help="Print machine-readable JSON.")
    ] = False,
) -> None:
    """List jars installed in plugins/ and mods/."""
    app_context = _ctx(context)
    with _errors():
        server = app_context.store.get(name)
        installed = app_context.content.installed(server)
    if as_json:
        console.print_json(
            data=[
                {
                    "file": item.filename,
                    "kind": item.kind.value,
                    "size": item.size,
                    "source": item.source.value if item.source else "",
                    "project_id": item.project_id,
                    "version_id": item.version_id,
                    "name": item.name,
                }
                for item in installed
            ]
        )
        return
    if not installed:
        console.print("[dim]No plugins or mods installed.[/dim]")
        return
    table = Table(title=f"Content in '{server.name}'", header_style="bold")
    table.add_column("File", style="bold")
    table.add_column("Kind")
    table.add_column("Source")
    table.add_column("Project")
    table.add_column("Version")
    table.add_column("Size", justify="right")
    for item in installed:
        table.add_row(
            escape(item.filename),
            item.kind.value,
            item.source.value if item.source else "-",
            escape(item.project_id or item.name),
            escape(item.version_id or "-"),
            f"{item.size:,} B",
        )
    console.print(table)


@content_app.command("remove")
def content_remove(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Server name.")],
    project: Annotated[str, typer.Argument(help="File name, project id or name.")],
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")
    ] = False,
) -> None:
    """Remove an installed plugin or mod."""
    app_context = _ctx(context)
    with _errors():
        server = app_context.store.get(name)
        if app_context.store.is_running(name)[0]:
            raise ServerError(
                f"Cannot remove content while '{name}' is running.",
                hint="Stop the server first.",
            )
        installed = app_context.content.installed(server)
        match = next(
            (
                item
                for item in installed
                if project.strip().lower()
                in {
                    item.filename.lower(),
                    Path(item.filename).stem.lower(),
                    item.project_id.lower(),
                    item.name.lower(),
                }
            ),
            None,
        )
        if match is None:
            raise ContentError(
                f"'{project}' is not installed on this server.",
                hint=f"Run `slime content list {name}` to see installed files.",
            )
        if not yes:
            if not sys.stdin.isatty():
                raise ServerError(
                    "Refusing to remove content without confirmation.",
                    hint="Pass --yes to remove non-interactively.",
                )
            if not Confirm.ask(
                f"Remove {match.filename} from '{server.name}'?", default=False
            ):
                console.print("Cancelled.")
                raise typer.Exit()
        removed = app_context.content.remove(server, match.filename)
    console.print(f"[green]Removed[/green] {escape(removed.filename)}.")


# ---------------------------------------------------------------------------
# Java commands
# ---------------------------------------------------------------------------


@java_app.command("list")
def java_list(
    context: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """List Java runtimes installed by Slime and on PATH."""
    app_context = _ctx(context)
    with _errors():
        installed = app_context.java_manager.installed()
        system = app_context.java_manager.system_java()

    if as_json:
        console.print_json(
            data={
                "installed": [_java_payload(install) for install in installed],
                "system": _java_payload(system) if system else None,
            }
        )
        return
    table = Table(title="Java runtimes", header_style="bold")
    table.add_column("Major", justify="right")
    table.add_column("Version")
    table.add_column("Source")
    table.add_column("Path")
    for install in installed:
        table.add_row(
            str(install.major),
            escape(install.version or "unknown"),
            install.source,
            escape(install.path),
        )
    if system:
        table.add_row(
            str(system.major),
            escape(system.version or "unknown"),
            "system",
            escape(system.path),
        )
    if not installed and not system:
        console.print("[dim]No Java runtimes found.[/dim]")
        console.print("Install one with: [cyan]slime java install 21[/cyan]")
        return
    console.print(table)


@java_app.command("releases")
def java_releases(
    context: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Show Java versions available from Adoptium."""
    app_context = _ctx(context)
    with _errors():
        releases = app_context.java_manager.client.releases()
        lts = set(app_context.java_manager.client.lts_releases())
        installed = {install.major for install in app_context.java_manager.installed()}

    if as_json:
        console.print_json(
            data=[
                {"major": major, "lts": major in lts, "installed": major in installed}
                for major in releases
            ]
        )
        return
    table = Table(title="Adoptium Temurin releases", header_style="bold")
    table.add_column("Major", justify="right")
    table.add_column("LTS")
    table.add_column("Installed")
    for major in releases:
        table.add_row(
            str(major),
            "[green]yes[/green]" if major in lts else "",
            "[green]yes[/green]" if major in installed else "",
        )
    console.print(table)
    console.print("Install with: [cyan]slime java install <major>[/cyan]")


@java_app.command("install")
def java_install(
    context: typer.Context,
    major: Annotated[int, typer.Argument(help="Java major version, e.g. 21.")],
    force: Annotated[
        bool, typer.Option("--force", help="Reinstall even if the version exists.")
    ] = False,
    os_name: Annotated[
        str | None, typer.Option("--os", help="Override the target OS (windows/linux/mac).")
    ] = None,
    arch: Annotated[
        str | None, typer.Option("--arch", help="Override the target architecture (x64/aarch64).")
    ] = None,
) -> None:
    """Download and install a Temurin JDK from Adoptium."""
    app_context = _ctx(context)
    with _errors():
        existing = app_context.java_manager.get(major)
        if existing is not None and not force:
            console.print(
                f"Java {major} is already installed: {escape(existing.path)}"
            )
            return

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(f"Downloading Temurin {major}…", total=None)

            def on_progress(done: int, total: int | None) -> None:
                progress.update(
                    task,
                    description=f"Downloading Temurin {major}…",
                    completed=done,
                    total=total,
                )

            install = app_context.java_manager.install(
                major,
                os_name=os_name,
                arch=arch,
                force=force,
                progress=on_progress,
            )

    console.print(
        Panel(
            f"[bold green]Java {install.major} installed[/bold green]\n\n"
            f"Version: {escape(install.version or 'unknown')}\n"
            f"Java:    {escape(install.path)}",
            title="Temurin",
            border_style="green",
        )
    )
    console.print(f"Servers that require Java {install.major} will use it automatically.")


@java_app.command("remove")
def java_remove(
    context: typer.Context,
    major: Annotated[int, typer.Argument(help="Java major version to remove.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
) -> None:
    """Remove a Java runtime installed by Slime."""
    app_context = _ctx(context)
    with _errors():
        install = app_context.java_manager.get(major)
        if install is None:
            raise JavaError(
                f"Slime does not manage a Java {major} runtime.",
                hint="Run `slime java list` to see installed runtimes.",
            )
        if not yes:
            if not sys.stdin.isatty():
                raise ServerError(
                    "Refusing to remove without confirmation.",
                    hint="Pass --yes to remove non-interactively.",
                )
            if not Confirm.ask(f"Remove Java {major} from {install.path}?", default=False):
                console.print("Cancelled.")
                raise typer.Exit()
        app_context.java_manager.remove(major)
    console.print(f"[green]Removed[/green] Java {major}.")


@java_app.command("which")
def java_which(
    context: typer.Context,
    major: Annotated[
        int | None, typer.Argument(help="Java major version (default: system Java).")
    ] = None,
    server: Annotated[
        str | None, typer.Option("--server", "-s", help="Show the Java a server will use.")
    ] = None,
) -> None:
    """Print the path to a Java executable (useful in scripts)."""
    app_context = _ctx(context)
    install: JavaInstall | None = None
    with _errors():
        if server:
            target = app_context.store.get(server)
            install = app_context.java_manager.require_for(target)
        elif major is not None:
            install = app_context.java_manager.get(major)
            if install is None:
                system = app_context.java_manager.system_java()
                install = system if system and system.major == major else None
            if install is None:
                raise JavaError(
                    f"Java {major} is not installed.",
                    hint=f"Install it with: slime java install {major}",
                )
        else:
            install = app_context.java_manager.system_java()
            if install is None:
                raise JavaError(
                    "No Java runtime was found on PATH or in JAVA_HOME.",
                    hint="Install one with: slime java install 21",
                )
    assert install is not None
    console.print(install.path)


# ---------------------------------------------------------------------------
# Config commands
# ---------------------------------------------------------------------------


@config_app.command("show")
def config_show(
    context: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Show settings and important paths."""
    app_context = _ctx(context)
    settings = app_context.config.settings
    paths = app_context.config.paths
    if as_json:
        console.print_json(
            data={
                "settings": asdict(settings),
                "paths": {
                    "home": str(paths.home),
                    "servers": str(paths.servers),
                    "java": str(paths.java),
                    "cache": str(paths.cache),
                    "logs": str(paths.logs),
                    "backups": str(paths.backups),
                    "config": str(paths.config_file),
                },
            }
        )
        return

    table = Table(title="Slime settings", header_style="bold")
    table.add_column("Setting", style="bold")
    table.add_column("Value")
    for field_name in Settings.__dataclass_fields__:
        table.add_row(field_name, escape(str(getattr(settings, field_name))))
    console.print(table)

    paths_table = Table(title="Paths", header_style="bold")
    paths_table.add_column("Location", style="bold")
    paths_table.add_column("Path")
    for label, value in (
        ("Home", paths.home),
        ("Servers", paths.servers),
        ("Java", paths.java),
        ("Cache", paths.cache),
        ("Logs", paths.logs),
        ("Backups", paths.backups),
        ("Config", paths.config_file),
    ):
        paths_table.add_row(label, escape(str(value)))
    console.print(paths_table)


@config_app.command("set")
def config_set(
    context: typer.Context,
    key: Annotated[str, typer.Argument(help="Setting name.")],
    value: Annotated[str, typer.Argument(help="New value.")],
) -> None:
    """Change one setting and save config.toml."""
    app_context = _ctx(context)
    with _errors():
        old = getattr(app_context.config.settings, key, None)
        new = app_context.config.set(key, value)
    console.print(f"[green]Updated[/green] {key}: {old!r} -> {new!r}")


@config_app.command("path")
def config_path(context: typer.Context) -> None:
    """Print the Slime home directory (useful in scripts)."""
    console.print(str(_ctx(context).config.paths.home))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Console-script entry point."""
    try:
        app()
    except SlimeError as error:
        _fail(error)


if __name__ == "__main__":  # pragma: no cover
    main()
