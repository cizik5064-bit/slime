"""Backup management screen for one server."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ClassVar

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static

from ...backup import BackupInfo, BackupManager
from ...errors import SlimeError
from ...models import Server
from .confirm import HoldConfirmScreen

if TYPE_CHECKING:
    from ..app import SlimeApp


class BackupScreen(Screen):
    """List, create, restore and delete backups for a server."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("escape", "close", "Back")
    ]

    def __init__(self, app: SlimeApp, server: Server) -> None:
        super().__init__()
        self.slime = app
        self.server = server
        self.manager = BackupManager(app.config, app.store)
        self._backups: list[BackupInfo] = []
        self._working = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="backup-body"):
            yield Static("", id="backup-title")
            yield Static("", id="backup-hint")
            yield DataTable(id="backup-table", cursor_type="row", zebra_stripes=True)
            yield Static("", id="backup-status")
            with Horizontal(id="backup-buttons"):
                yield Button("Create backup", id="backup-create", variant="success")
                yield Button("Restore", id="backup-restore", variant="warning")
                yield Button("Delete", id="backup-delete", variant="error")
                yield Button("Back", id="backup-close")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#backup-title", Static).update(
            f"[bold]Backups[/bold] · {escape(self.server.name)}"
        )
        table = self.query_one("#backup-table", DataTable)
        table.add_columns("Backup", "Created (UTC)", "Size", "Version", "Files", "Note")
        self._reload()

    # ------------------------------------------------------------------ state
    def _server_running(self) -> bool:
        process = self.slime.get_process(self.server.name)
        if process is not None:
            return process.is_running
        return self.slime.store.is_running(self.server.name)[0]

    def _selected_backup(self) -> BackupInfo | None:
        if not self._backups:
            return None
        table = self.query_one("#backup-table", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._backups):
            return self._backups[row]
        return None

    def _update_controls(self) -> None:
        running = self._server_running()
        selected = self._selected_backup()
        self.query_one("#backup-create", Button).disabled = running or self._working
        self.query_one("#backup-restore", Button).disabled = (
            running or selected is None or self._working
        )
        self.query_one("#backup-delete", Button).disabled = (
            selected is None or self._working
        )
        if running:
            hint = (
                "Stop the server before creating or restoring a backup. "
                "Consistency is guaranteed only while it is stopped."
            )
        else:
            hint = (
                "Backups are stored in "
                f"[cyan]{escape(str(self.manager.directory(self.server.name)))}[/cyan] "
                "as maximally compressed .7z archives."
            )
        self.query_one("#backup-hint", Static).update(hint)

    def _reload(self) -> None:
        self.query_one("#backup-status", Static).update("Loading backups…")
        self.slime.run_worker(
            self._load(),
            exclusive=True,
            group="backup-load",
            exit_on_error=False,
        )

    async def _load(self) -> None:
        try:
            backups = await asyncio.to_thread(self.manager.list, self.server.name)
        except (SlimeError, OSError) as error:
            if self.is_mounted:
                self.slime.notify_error(error)
            return
        if not self.is_mounted:
            return
        self._backups = backups
        table = self.query_one("#backup-table", DataTable)
        table.clear()
        for info in backups:
            table.add_row(
                info.identifier,
                info.created_label,
                info.size_label,
                info.minecraft_version or "-",
                str(info.files or "-"),
                info.note,
                key=info.identifier,
            )
        if backups:
            self.query_one("#backup-status", Static).update(
                f"{len(backups)} backup(s)."
            )
        else:
            self.query_one("#backup-status", Static).update(
                "No backups yet. Create one while the server is stopped."
            )
        self._update_controls()

    # --------------------------------------------------------------- controls
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "backup-create":
            self._start_create()
        elif button_id == "backup-restore":
            selected = self._selected_backup()
            if selected is not None:
                self._confirm_restore(selected)
        elif button_id == "backup-delete":
            selected = self._selected_backup()
            if selected is not None:
                self._confirm_delete(selected)
        elif button_id == "backup-close":
            self.action_close()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_controls()

    def action_close(self) -> None:
        if not self._working:
            self.slime.pop_screen()

    # ----------------------------------------------------------------- create
    def _start_create(self) -> None:
        if self._server_running():
            self.slime.notify(
                "Stop the server before creating a backup.", severity="warning"
            )
            return
        self._working = True
        self.query_one("#backup-status", Static).update(
            "Compressing the world, plugins and configs with 7z…"
        )
        self._update_controls()
        self.slime.run_worker(
            self._create(), exclusive=True, group="backup", exit_on_error=False
        )

    async def _create(self) -> None:
        try:
            info = await asyncio.to_thread(self.manager.create, self.server)
        except (SlimeError, OSError) as error:
            self._working = False
            self._update_controls()
            self.slime.notify_error(error)
            return
        self._working = False
        self.slime.notify(
            f"Backup {info.identifier} created ({info.size_label}).", timeout=5
        )
        self._reload()

    # ---------------------------------------------------------------- restore
    def _confirm_restore(self, info: BackupInfo) -> None:
        self.slime.push_screen(
            HoldConfirmScreen(
                f"Restore backup {info.identifier} into '{self.server.name}'?\n\n"
                "Worlds, plugins and configs from the backup replace the current "
                "ones. This cannot be undone.",
                cancel_label="Cancel",
            ),
            lambda confirmed: self._on_restore(confirmed, info),
        )

    def _on_restore(self, confirmed: bool | None, info: BackupInfo) -> None:
        if not confirmed:
            return
        if self._server_running():
            self.slime.notify(
                "Stop the server before restoring a backup.", severity="warning"
            )
            return
        self._working = True
        self.query_one("#backup-status", Static).update(
            f"Restoring {info.identifier}…"
        )
        self._update_controls()
        self.slime.run_worker(
            self._restore(info),
            exclusive=True,
            group="backup",
            exit_on_error=False,
        )

    async def _restore(self, info: BackupInfo) -> None:
        try:
            restored = await asyncio.to_thread(
                self.manager.restore, self.server, info.identifier
            )
        except (SlimeError, OSError) as error:
            self._working = False
            self._update_controls()
            self.slime.notify_error(error)
            return
        self._working = False
        self.slime.notify(
            f"Restored {restored} file(s) from {info.identifier}.", timeout=5
        )
        self._reload()

    # ----------------------------------------------------------------- delete
    def _confirm_delete(self, info: BackupInfo) -> None:
        self.slime.push_screen(
            HoldConfirmScreen(
                f"Delete backup {info.identifier} ({info.size_label})?\n\n"
                "The archive will be permanently removed.",
                cancel_label="Cancel",
            ),
            lambda confirmed: self._on_delete(confirmed, info),
        )

    def _on_delete(self, confirmed: bool | None, info: BackupInfo) -> None:
        if not confirmed:
            return
        self._working = True
        self.query_one("#backup-status", Static).update(
            f"Deleting {info.identifier}…"
        )
        self._update_controls()
        self.slime.run_worker(
            self._delete(info), exclusive=True, group="backup", exit_on_error=False
        )

    async def _delete(self, info: BackupInfo) -> None:
        try:
            await asyncio.to_thread(self.manager.delete, self.server.name, info.identifier)
        except (SlimeError, OSError) as error:
            self._working = False
            self._update_controls()
            self.slime.notify_error(error)
            return
        self._working = False
        self.slime.notify(f"Deleted backup {info.identifier}.", timeout=4)
        self._reload()


__all__ = ["BackupScreen"]
