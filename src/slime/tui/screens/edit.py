"""Edit-server screen with General, server.properties and Dangerous tabs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from ...errors import SlimeError, ValidationError
from ...models import (
    Server,
    parse_launch_flags,
    validate_cpu_cores,
    validate_java_major,
    validate_memory,
    validate_port,
    validate_server_name,
)
from ...properties import (
    DEFAULT_SERVER_PROPERTIES,
    read_properties,
    write_properties,
)
from .confirm import HoldConfirmScreen

if TYPE_CHECKING:
    from ..app import SlimeApp

JAVA_MAJORS = (8, 11, 16, 17, 21, 25)

#: Shown next to settings that can break a server when changed carelessly.
DANGER_HINT = "If you don't know, don't change it!"


class EditServerScreen(Screen[Server | str | None]):
    """Full-screen editor for an existing server.

    ``dismiss`` returns the updated :class:`Server` after a successful save,
    the string ``"deleted"`` after deletion, or ``None`` when cancelled.
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(self, app: SlimeApp, server: Server) -> None:
        super().__init__()
        self.slime = app
        self.server = server
        self._properties_path = app.store.path(server.name) / "server.properties"
        if server.is_proxy:
            self._properties: dict[str, str] = {}
        elif self._properties_path.is_file():
            self._properties = read_properties(self._properties_path)
        else:
            self._properties = dict(DEFAULT_SERVER_PROPERTIES)
        if not server.is_proxy and not self._properties:
            self._properties = dict(DEFAULT_SERVER_PROPERTIES)
        self._property_keys = list(self._properties)
        self._busy = False

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        min_memory = (
            self.server.min_memory_mb
            if self.server.min_memory_mb is not None
            else self.server.memory_mb
        )
        flags = "\n".join(self.server.extra_args)
        cpu = "" if self.server.cpu_cores is None else str(self.server.cpu_cores)
        java_path = self.server.java_path or ""

        yield Header(show_clock=True)
        with Vertical(id="edit-body"):
            yield Static(
                f"[bold]{escape(self.server.name)}[/bold] · edit settings",
                id="edit-title",
            )
            with TabbedContent(initial="general", id="edit-tabs"):
                with TabPane("General", id="general"), VerticalScroll(
                    id="general-scroll"
                ):
                        yield Label("Server name")
                        yield Input(value=self.server.name, id="edit-name")

                        with Horizontal(classes="field-row"):
                            with Vertical(classes="field"):
                                yield Label("Minimum RAM (MB)")
                                yield Input(value=str(min_memory), id="edit-min-memory")
                            with Vertical(classes="field"):
                                yield Label("Maximum RAM (MB)")
                                yield Input(
                                    value=str(self.server.memory_mb),
                                    id="edit-max-memory",
                                )

                        yield Label("Launch flags")
                        yield Static(DANGER_HINT, classes="danger-hint")
                        yield TextArea(flags, id="edit-flags")
                        yield Static(
                            "One flag per line, separated by spaces, or joined with "
                            "a trailing backslash. RAM, CPU cores, nogui, recovery "
                            "flags and Aikar's defaults are added automatically and "
                            "are not shown here. Takes effect on the next start.",
                            classes="hint",
                        )

                        yield Label("CPU cores (blank = automatic)")
                        yield Static(DANGER_HINT, classes="danger-hint")
                        yield Input(
                            value=cpu,
                            placeholder="automatic",
                            id="edit-cpu-cores",
                        )

                        yield Label("Java path (blank = automatic)")
                        yield Static(DANGER_HINT, classes="danger-hint")
                        yield Input(
                            value=java_path,
                            placeholder=r"C:\Program Files\Java\...\bin\java.exe",
                            id="edit-java-path",
                        )

                        yield Label("Java version")
                        yield Static(DANGER_HINT, classes="danger-hint")
                        yield Select(
                            [(f"Java {major}", str(major)) for major in JAVA_MAJORS],
                            value=str(self.server.java_major),
                            id="edit-java-major",
                            allow_blank=False,
                        )
                        yield Static(
                            "These settings are used the next time the server starts.",
                            classes="hint",
                        )

                with TabPane("server.properties", id="properties"):
                    if self.server.is_proxy:
                        yield Static(
                            f"{self.server.project.display_name} uses its own "
                            "configuration file instead of server.properties.",
                            classes="hint",
                        )
                    else:
                        yield Static(
                            escape(str(self._properties_path)),
                            classes="dialog-subtitle",
                        )
                        with VerticalScroll(id="properties-list"):
                            for key, value in self._properties.items():
                                with Horizontal(classes="property-row"):
                                    yield Label(key, classes="property-key")
                                    yield Input(value=value, classes="property-value")

                with TabPane("Dangerous", id="dangerous"), VerticalScroll(
                    id="dangerous-scroll"
                ):
                        yield Static("Danger zone", classes="dialog-title")
                        yield Static(
                            "Reset world deletes the overworld, nether and end so "
                            "the server generates a fresh world on the next start.",
                            classes="dialog-subtitle",
                        )
                        yield Button(
                            "Reset world",
                            id="edit-reset-world",
                            variant="warning",
                        )
                        yield Static(
                            "Deleting the server removes its jar, configuration, "
                            "world and all backups stored in the server directory. "
                            "This cannot be undone.",
                            classes="dialog-subtitle",
                        )
                        yield Button(
                            "Delete server",
                            id="edit-delete",
                            variant="error",
                        )

            with Horizontal(id="edit-buttons"):
                yield Button("Save", id="edit-save", variant="success")
                yield Button("Cancel", id="edit-cancel")

        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#edit-name", Input).focus()

    # ----------------------------------------------------------------- actions
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if self._busy:
            return
        if button_id == "edit-save":
            self.save()
        elif button_id == "edit-cancel":
            self.dismiss(None)
        elif button_id == "edit-reset-world":
            self.confirm_reset_world()
        elif button_id == "edit-delete":
            self.confirm_delete()

    def action_cancel(self) -> None:
        if not self._busy:
            self.dismiss(None)

    def action_save(self) -> None:
        if not self._busy:
            self.save()

    # -------------------------------------------------------------------- save
    def save(self) -> None:
        try:
            name = validate_server_name(self.query_one("#edit-name", Input).value)
            max_memory = validate_memory(
                int(self.query_one("#edit-max-memory", Input).value.strip())
            )
            min_raw = self.query_one("#edit-min-memory", Input).value.strip()
            min_memory = validate_memory(int(min_raw) if min_raw else max_memory)
            if min_memory > max_memory:
                raise ValidationError(
                    "Minimum RAM cannot be greater than maximum RAM."
                )

            cpu_raw = self.query_one("#edit-cpu-cores", Input).value.strip()
            cpu_cores = None
            if cpu_raw:
                cpu_cores = validate_cpu_cores(int(cpu_raw))

            java_path_raw = self.query_one("#edit-java-path", Input).value.strip()
            java_path: str | None = None
            if java_path_raw:
                candidate = Path(java_path_raw).expanduser()
                if not candidate.is_file():
                    raise ValidationError(
                        f"Java executable not found: {candidate}",
                        hint="Leave the field blank to let Slime pick a runtime.",
                    )
                java_path = str(candidate)

            java_value = self.query_one("#edit-java-major", Select).value
            if java_value is Select.BLANK:
                raise ValidationError("Choose a Java version.")
            java_major = validate_java_major(int(str(java_value)))

            flags = parse_launch_flags(self.query_one("#edit-flags", TextArea).text)

            properties = self._read_property_inputs()
            port = self.server.port
            if "server-port" in properties:
                port_raw = properties["server-port"].strip()
                if not port_raw:
                    raise ValidationError("server-port cannot be empty.")
                port = validate_port(int(port_raw))

            old_name = self.server.name
            if name != old_name:
                process = self.slime.get_process(old_name)
                if process is not None and process.is_running:
                    raise SlimeError(
                        "Stop the server before renaming it.",
                        hint="Use the Stop button, then edit the name again.",
                    )
                self.slime.store.rename(old_name, name)
                self.server.name = name
                self._properties_path = self.slime.store.path(name) / "server.properties"
                self.slime.processes.pop(old_name, None)

            self.server.min_memory_mb = min_memory
            self.server.memory_mb = max_memory
            self.server.cpu_cores = cpu_cores
            self.server.java_path = java_path
            self.server.java_major = java_major
            self.server.extra_args = flags
            self.server.port = port
            self.slime.store.save(self.server)

            if not self.server.is_proxy and properties:
                write_properties(
                    self._properties_path,
                    properties,
                    header="#Minecraft server properties\n#Edited by Slime",
                    merge=False,
                )
        except (ValueError, SlimeError) as error:
            self._notify_error(error)
            return
        except OSError as error:
            self._notify_error(error)
            return

        self.slime.refresh_dashboard()
        self.slime.notify(f"Server '{self.server.name}' saved.", timeout=4)
        self.dismiss(self.server)

    def _read_property_inputs(self) -> dict[str, str]:
        if self.server.is_proxy:
            return {}
        inputs = [
            widget
            for widget in self.query(Input)
            if widget.has_class("property-value")
        ]
        return {
            key: widget.value
            for key, widget in zip(self._property_keys, inputs, strict=False)
        }

    # ------------------------------------------------------------------ delete
    def confirm_delete(self) -> None:
        self.slime.push_screen(
            HoldConfirmScreen(
                f"Delete '{self.server.name}' and all of its world files? "
                "This cannot be undone.",
                cancel_label="Keep server",
            ),
            self._on_delete_confirmed,
        )

    def _on_delete_confirmed(self, confirmed: bool | None) -> None:
        if confirmed:
            self._delete_server()

    @work(exclusive=True, group="edit-delete")
    async def _delete_server(self) -> None:
        self._busy = True
        self._set_controls_disabled(True)
        process = self.slime.get_process(self.server.name)
        try:
            if process is not None and process.is_running:
                await process.stop()
            await asyncio.to_thread(self.slime.store.delete, self.server.name)
        except (SlimeError, OSError) as error:
            self._busy = False
            self._set_controls_disabled(False)
            self._notify_error(error)
            return
        self.slime.processes.pop(self.server.name, None)
        self.slime.refresh_dashboard()
        self.slime.notify(f"Server '{self.server.name}' deleted.", timeout=4)
        self.dismiss("deleted")

    # ------------------------------------------------------------------- world
    def confirm_reset_world(self) -> None:
        self.slime.push_screen(
            HoldConfirmScreen(
                f"Reset the world of '{self.server.name}'?\n\n"
                "The overworld, nether and end will be deleted and generated "
                "again on the next start. This cannot be undone.",
                cancel_label="Keep world",
            ),
            self._on_reset_world_confirmed,
        )

    def _on_reset_world_confirmed(self, confirmed: bool | None) -> None:
        if confirmed:
            self._reset_world()

    @work(exclusive=True, group="edit-reset-world")
    async def _reset_world(self) -> None:
        process = self.slime.get_process(self.server.name)
        if process is not None and process.is_running:
            self.slime.notify(
                "Stop the server before resetting its world.",
                severity="error",
                timeout=6,
            )
            return
        self._busy = True
        self._set_controls_disabled(True)
        try:
            removed = await asyncio.to_thread(
                self.slime.store.reset_world, self.server.name
            )
        except OSError as error:
            self._busy = False
            self._set_controls_disabled(False)
            self._notify_error(error)
            return
        self.server.world_reset_suggested = False
        try:
            self.slime.store.save(self.server)
        except (SlimeError, OSError) as error:
            self._notify_error(error)
        self._busy = False
        self._set_controls_disabled(False)
        if removed:
            self.slime.notify(
                f"World reset: removed {len(removed)} folder(s).", timeout=5
            )
        else:
            self.slime.notify("No world folders were found.", timeout=5)

    def _set_controls_disabled(self, disabled: bool) -> None:
        for widget in self.query("Input, Select, TextArea, Button"):
            widget.disabled = disabled

    # ------------------------------------------------------------------ errors
    def _notify_error(self, error: Exception) -> None:
        message = error.message if isinstance(error, SlimeError) else str(error)
        hint = error.hint if isinstance(error, SlimeError) else None
        self.slime.notify(
            message + (f"\n{hint}" if hint else ""),
            severity="error",
            timeout=8,
        )


__all__ = ["EditServerScreen"]
