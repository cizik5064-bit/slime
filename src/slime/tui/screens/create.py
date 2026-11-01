"""Create-server wizard."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ClassVar

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, Switch

from ...errors import SlimeError
from ...models import PROJECTS, Project, required_java_major
from ...provision import CreateRequest

if TYPE_CHECKING:
    from ..app import SlimeApp


class CreateServerScreen(ModalScreen):
    """Modal form that provisions a new server without leaving the TUI."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel")
    ]

    def __init__(self, app: SlimeApp) -> None:
        super().__init__()
        self.slime = app
        self._project = Project.PAPER
        self._busy = False

    def compose(self) -> ComposeResult:
        settings = self.slime.config.settings
        with Container(id="create-dialog"):
            yield Static("Create a server", classes="dialog-title")
            yield Static(
                "Slime downloads the jar from PaperMC and prepares the server "
                "directory for you.",
                classes="dialog-subtitle",
            )

            yield Label("Name")
            yield Input(placeholder="my-server", id="name")

            yield Label("Project")
            yield Select(
                [(project.display_name, project.value) for project in PROJECTS],
                value=Project.PAPER.value,
                id="project",
                allow_blank=False,
            )

            yield Label("Minecraft version")
            yield Input(placeholder="latest, or e.g. 1.21.4", id="version")
            yield Label("Suggested versions")
            yield Select([("latest", "")], value="", id="version-select", allow_blank=False)

            yield Label("Build channel")
            yield Select(
                [
                    ("Stable (recommended)", "STABLE"),
                    ("Beta", "BETA"),
                    ("Alpha", "ALPHA"),
                    ("Any", "ANY"),
                ],
                value="STABLE",
                id="channel",
                allow_blank=False,
            )

            yield Label("Build number (optional)")
            yield Input(placeholder="latest", id="build")

            with Horizontal(classes="field-row"):
                with Container(classes="field"):
                    yield Label("Memory (MB)")
                    yield Input(value=str(settings.default_memory_mb), id="memory")
                with Container(classes="field"):
                    yield Label("Port")
                    yield Input(value=str(settings.default_port), id="port")

            yield Label("Java")
            yield Select(
                [
                    ("Auto — required version (recommended)", "auto"),
                    ("Java 8", "8"),
                    ("Java 11", "11"),
                    ("Java 17", "17"),
                    ("Java 21", "21"),
                    ("Java 25", "25"),
                ],
                value="auto",
                id="java",
                allow_blank=False,
            )
            yield Static("", id="java-hint", classes="hint")

            with Horizontal(classes="switch-row"):
                yield Label("Accept the Minecraft EULA")
                yield Switch(id="eula")
            yield Static(
                "https://aka.ms/MinecraftEULA — required for Paper and Folia.",
                classes="hint",
            )

            yield Static("", id="create-status")
            with Horizontal(id="create-buttons"):
                yield Button("Create server", id="create", variant="success")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()
        self._update_project(Project.PAPER)
        self.load_versions(Project.PAPER)

    # ---------------------------------------------------------------- helpers
    def _set_status(self, message: str, *, error: bool = False) -> None:
        style = "red" if error else "yellow"
        self.query_one("#create-status", Static).update(
            f"[{style}]{escape(message)}[/{style}]" if message else ""
        )

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in self.query("Input, Select, Switch, Button"):
            widget.disabled = busy
        if not busy:
            self._update_project(self._project)

    def _required_java(self) -> int:
        version = self.query_one("#version", Input).value.strip()
        if self._project.is_proxy:
            return required_java_major(self._project, "")
        if version:
            return required_java_major(self._project, version)
        return 21

    def _update_java_hint(self) -> None:
        major = self._required_java()
        self.query_one("#java-hint", Static).update(
            f"Recommended for this project/version: Java {major}."
        )

    def _update_project(self, project: Project) -> None:
        self._project = project
        eula = self.query_one("#eula", Switch)
        eula.disabled = project.is_proxy
        if project.is_proxy:
            eula.value = False
        self._update_java_hint()

    def _update_progress(self, stage: str, done: int, total: int | None) -> None:
        if total and total > 0:
            self._set_status(f"{stage}: {done / total:.0%}")
        else:
            self._set_status(stage)

    # ---------------------------------------------------------------- versions
    @work(exclusive=True, group="versions")
    async def load_versions(self, project: Project) -> None:
        select = self.query_one("#version-select", Select)
        try:
            versions = await asyncio.to_thread(
                self.slime.papermc.versions, project.value
            )
        except SlimeError as error:
            select.set_options([("latest", "")])
            select.value = ""
            self._set_status(
                f"Could not load versions: {error.message}. Type one manually."
            )
            return
        options = [("latest", "")] + [(version, version) for version in versions[:60]]
        select.set_options(options)
        select.value = ""
        self._set_status("")

    # ------------------------------------------------------------------ events
    def on_select_changed(self, event: Select.Changed) -> None:
        select_id = event.select.id
        value = event.value
        if select_id == "version-select":
            if value is Select.BLANK:
                return
            self.query_one("#version", Input).value = (
                "" if value in (None, "", "latest") else str(value)
            )
            self._update_java_hint()
        elif select_id == "project":
            if value is Select.BLANK:
                return
            project = Project.parse(str(value))
            self._update_project(project)
            self.load_versions(project)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "version":
            self._update_java_hint()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if self._busy:
            return
        if event.button.id == "create":
            self.create_server()
        elif event.button.id == "cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        if not self._busy:
            self.dismiss(None)

    # ------------------------------------------------------------------ create
    @work(exclusive=True, group="create")
    async def create_server(self) -> None:
        try:
            name = self.query_one("#name", Input).value.strip()
            project_value = self.query_one("#project", Select).value
            if project_value is Select.BLANK:
                raise ValueError("Choose a project.")
            project = Project.parse(str(project_value))

            version = self.query_one("#version", Input).value.strip()
            channel_value = self.query_one("#channel", Select).value
            channel = "STABLE" if channel_value is Select.BLANK else str(channel_value)

            build_raw = self.query_one("#build", Input).value.strip()
            build = int(build_raw) if build_raw else None
            memory = int(self.query_one("#memory", Input).value.strip())
            port = int(self.query_one("#port", Input).value.strip())

            java_value = self.query_one("#java", Select).value
            java = (
                None
                if java_value in (Select.BLANK, None, "", "auto")
                else int(str(java_value))
            )

            eula = self.query_one("#eula", Switch).value
            request = CreateRequest(
                name=name,
                project=project,
                version=version,
                build=build,
                channel=channel,
                memory_mb=memory,
                port=port,
                java_major=java,
                accept_eula=bool(eula),
            )
        except (ValueError, SlimeError) as error:
            self._set_status(str(error), error=True)
            return

        self._set_busy(True)
        self._set_status("Contacting PaperMC…")

        def on_progress(stage: str, done: int, total: int | None) -> None:
            self.slime.call_from_thread(self._update_progress, stage, done, total)

        try:
            server = await asyncio.to_thread(
                self.slime.provisioner.create, request, progress=on_progress
            )
        except (SlimeError, OSError) as error:
            message = error.message if isinstance(error, SlimeError) else str(error)
            self._set_busy(False)
            self._set_status(f"Could not create the server: {message}", error=True)
            return
        except Exception as error:  # pragma: no cover - unexpected failures
            self._set_busy(False)
            self._set_status(f"Unexpected error: {error}", error=True)
            return

        self._set_busy(False)
        self.dismiss(server)
