"""Headless tests for the backup screen."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Button, DataTable

from slime.config import Config
from slime.models import Server
from slime.tui.app import SlimeApp
from slime.tui.screens.backup import BackupScreen


def make_server() -> Server:
    return Server(
        name="survival",
        project="paper",
        minecraft_version="1.21.4",
        build=232,
        java_major=21,
        memory_mb=2048,
        port=25565,
    )


def prepare_server(app: SlimeApp, server: Server) -> Path:
    app.store.save(server)
    directory = app.store.path(server.name)
    (directory / "world").mkdir()
    (directory / "world" / "level.dat").write_text("level", encoding="utf-8")
    (directory / "server.properties").write_text(
        "level-name=world\n", encoding="utf-8"
    )
    return directory


async def test_backup_screen_creates_a_backup(tmp_path: Path) -> None:
    app = SlimeApp(Config(tmp_path / "home"))
    server = make_server()
    prepare_server(app, server)

    async with app.run_test() as pilot:
        app.push_screen(BackupScreen(app, server))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BackupScreen)

        table = screen.query_one("#backup-table", DataTable)
        assert table.row_count == 0

        await pilot.click("#backup-create")
        for _ in range(50):
            await asyncio.sleep(0.05)
            await pilot.pause()
            if table.row_count:
                break

        assert table.row_count == 1
        backups = list((app.config.paths.backups / server.name).glob("*.7z"))
        assert len(backups) == 1
        assert screen.query_one("#backup-table", DataTable).row_count == 1


async def test_backup_screen_disables_actions_while_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = SlimeApp(Config(tmp_path / "home"))
    server = make_server()
    prepare_server(app, server)
    monkeypatch.setattr(app.store, "is_running", lambda name: (True, 1234))

    async with app.run_test() as pilot:
        app.push_screen(BackupScreen(app, server))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BackupScreen)

        assert screen.query_one("#backup-create", Button).disabled is True
        hint = screen.query_one("#backup-hint").render()
        assert "Stop the server" in str(hint)
