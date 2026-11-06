"""Java runtime manager screen."""

from __future__ import annotations

import asyncio
import contextlib
import platform
from typing import TYPE_CHECKING, ClassVar

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Select, Static

from ...errors import SlimeError
from ...models import JavaInstall
from .confirm import ConfirmScreen

if TYPE_CHECKING:
    from ..app import SlimeApp

FALLBACK_RELEASES = [8, 11, 16, 17, 21, 25]


class JavaScreen(Screen):
    """List, install and remove Temurin JDKs."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("escape", "back", "Back"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, app: SlimeApp) -> None:
        super().__init__()
        self.slime = app
        self._installed: list[JavaInstall] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="java-body"):
            yield Static("Java runtimes", id="java-title")
            yield Static(
                "Slime installs Eclipse Temurin JDKs from the Adoptium API. "
                "Each server picks the runtime matching its required Java major.",
                classes="dialog-subtitle",
            )
            yield DataTable(id="java-table", cursor_type="row", zebra_stripes=True)
            with Horizontal(id="java-controls"):
                yield Select(
                    [(f"Java {major}", str(major)) for major in FALLBACK_RELEASES],
                    value="21",
                    id="java-major",
                    allow_blank=False,
                )
                yield Button("Install", id="install", variant="success")
                yield Button("Remove selected", id="remove", variant="error")
                yield Button("Refresh", id="refresh")
                yield Button("Back", id="back")
            yield Static("", id="java-status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#java-table", DataTable)
        table.add_columns("Major", "Version", "Source", "Path", "Platform")
        self.refresh_data()
        self.load_releases()

    # ------------------------------------------------------------------- data
    def refresh_data(self) -> None:
        table = self.query_one("#java-table", DataTable)
        table.clear()
        self._installed = self.slime.java_manager.installed()
        for install in self._installed:
            table.add_row(
                str(install.major),
                install.version or "unknown",
                install.source,
                escape(install.path),
                f"{install.os}/{install.arch}" if install.os else "",
                key=str(install.major),
            )
        system = self.slime.java_manager.system_java()
        if system is not None:
            table.add_row(
                str(system.major),
                system.version or "unknown",
                "system",
                escape(system.path),
                "",
                key=f"system-{system.major}",
            )
        if self._installed:
            self.query_one("#java-status", Static).update(
                f"{len(self._installed)} runtime(s) managed by Slime."
            )
        else:
            self.query_one("#java-status", Static).update(
                "No managed runtimes yet. Install one to get started."
            )

    @work(exclusive=True, group="releases")
    async def load_releases(self) -> None:
        select = self.query_one("#java-major", Select)
        try:
            releases = await asyncio.to_thread(
                self.slime.java_manager.client.releases
            )
            lts = await asyncio.to_thread(
                self.slime.java_manager.client.lts_releases
            )
        except SlimeError as error:
            if not self._can_update(select):
                return
            try:
                select.set_options(
                    [(f"Java {major}", str(major)) for major in FALLBACK_RELEASES]
                )
                select.value = "21"
                self.query_one("#java-status", Static).update(
                    f"Adoptium unavailable: {escape(error.message)}. Showing common versions."
                )
            except NoMatches:
                return
            return
        # The screen may have been closed while Adoptium was queried.
        if not self._can_update(select):
            return
        lts_set = set(lts)
        preferred = "21" if 21 in releases else str(releases[-1])
        try:
            select.set_options(
                [
                    (
                        f"Java {major}" + (" · LTS" if major in lts_set else ""),
                        str(major),
                    )
                    for major in releases
                ]
            )
            select.value = preferred
        except NoMatches:
            # The Select's internal overlay is gone during a screen pop.
            return

    def _can_update(self, select: Select) -> bool:
        return self.is_current and select.is_mounted

    # ----------------------------------------------------------------- events
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "install":
            self.install_selected()
        elif button_id == "remove":
            self.confirm_remove()
        elif button_id == "refresh":
            self.action_refresh()
        elif button_id == "back":
            self.action_back()

    def action_refresh(self) -> None:
        self.refresh_data()
        self.load_releases()
        self.slime.notify("Java list refreshed.", timeout=2)

    def action_back(self) -> None:
        self.slime.pop_screen()

    # ---------------------------------------------------------------- install
    @work(exclusive=True, group="java-install")
    async def install_selected(self) -> None:
        value = self.query_one("#java-major", Select).value
        if value is Select.BLANK:
            self.slime.notify("Choose a Java version first.", severity="warning")
            return
        major = int(str(value))
        self.query_one("#java-status", Static).update(f"Downloading Java {major}…")

        def on_progress(done: int, total: int | None) -> None:
            if total and total > 0:
                text = f"Downloading Java {major}… {done / total:.0%}"
            else:
                text = f"Downloading Java {major}…"
            self.slime.call_from_thread(self._set_status, text)

        try:
            install = await asyncio.to_thread(
                self.slime.java_manager.install, major, progress=on_progress
            )
        except (SlimeError, OSError) as error:
            message = error.message if isinstance(error, SlimeError) else str(error)
            self._set_status(f"Install failed: {message}")
            self.slime.notify_error(error)
            return
        self._set_status(f"Java {install.major} installed: {install.path}")
        self.slime.notify(f"Java {install.major} installed.", timeout=4)
        self.refresh_data()

    def _set_status(self, message: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#java-status", Static).update(escape(message))

    # ----------------------------------------------------------------- remove
    def confirm_remove(self) -> None:
        table = self.query_one("#java-table", DataTable)
        row = table.cursor_row
        if not isinstance(row, int) or not 0 <= row < len(self._installed):
            self.slime.notify(
                "Select a runtime installed by Slime to remove.", severity="warning"
            )
            return
        install = self._installed[row]
        self.slime.push_screen(
            ConfirmScreen(
                f"Remove Java {install.major} from {install.path}?",
                confirm_label="Remove Java",
            ),
            lambda confirmed: self._remove_confirmed(install, confirmed),
        )

    def _remove_confirmed(self, install: JavaInstall, confirmed: bool | None) -> None:
        if not confirmed:
            return
        try:
            self.slime.java_manager.remove(install.major)
        except (SlimeError, OSError) as error:
            self.slime.notify_error(error)
            return
        self.slime.notify(f"Java {install.major} removed.", timeout=4)
        self.refresh_data()

    # ------------------------------------------------------------------ misc
    @staticmethod
    def platform_label() -> str:
        return f"{platform.system()} {platform.machine()}"


__all__ = ["JavaScreen"]
