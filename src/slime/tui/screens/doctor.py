"""Environment diagnostics screen."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ClassVar

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static

from ...checks import CheckResult, CheckStatus, run_checks, summarize

if TYPE_CHECKING:
    from ..app import SlimeApp

_STATUS_COLORS = {
    CheckStatus.OK: "green",
    CheckStatus.INFO: "cyan",
    CheckStatus.WARN: "yellow",
    CheckStatus.FAIL: "red",
}


class DoctorScreen(Screen):
    """Run the same checks as ``slime doctor`` and display the results."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("escape", "back", "Back"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, app: SlimeApp) -> None:
        super().__init__()
        self.slime = app

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="doctor-body"):
            yield Static("Environment check", id="doctor-title")
            yield Static(
                "Python, OS, disk, Java, ports, EULA and server files. "
                "Warnings do not block startup; errors usually do.",
                classes="dialog-subtitle",
            )
            yield DataTable(id="checks-table", cursor_type="row", zebra_stripes=True)
            with Horizontal(id="doctor-controls"):
                yield Button("Run again", id="refresh", variant="primary")
                yield Button("Back", id="back")
            yield Static("", id="doctor-summary")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#checks-table", DataTable)
        table.add_columns("Scope", "Check", "Status", "Details", "Hint")
        self.run_checks_now()

    @work(exclusive=True, group="checks")
    async def run_checks_now(self) -> None:
        self.query_one("#doctor-summary", Static).update("Running checks…")
        try:
            results = await asyncio.to_thread(
                run_checks,
                self.slime.config,
                self.slime.store,
                self.slime.java_manager,
            )
        except Exception as error:  # pragma: no cover - defensive
            self.query_one("#doctor-summary", Static).update(
                f"[red]Check failed: {escape(str(error))}[/red]"
            )
            return

        table = self.query_one("#checks-table", DataTable)
        table.clear()
        for result in results:
            table.add_row(
                result.scope,
                escape(result.title),
                self._status(result),
                escape(result.message),
                escape(result.hint or ""),
            )

        counts = summarize(results)
        self.query_one("#doctor-summary", Static).update(
            f"[green]{counts[CheckStatus.OK]} ok[/green]  "
            f"[cyan]{counts[CheckStatus.INFO]} info[/cyan]  "
            f"[yellow]{counts[CheckStatus.WARN]} warning(s)[/yellow]  "
            f"[red]{counts[CheckStatus.FAIL]} error(s)[/red]"
        )

    @staticmethod
    def _status(result: CheckResult) -> str:
        color = _STATUS_COLORS[result.status]
        return f"[{color}]{result.status.value.upper()}[/{color}]"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh":
            self.run_checks_now()
        elif event.button.id == "back":
            self.action_back()

    def action_refresh(self) -> None:
        self.run_checks_now()

    def action_back(self) -> None:
        self.slime.pop_screen()
