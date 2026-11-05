"""Headless tests for dashboard navigation and status labels."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import DataTable, Static

from slime.config import Config
from slime.models import Server
from slime.tui.app import SlimeApp
from slime.tui.screens.create import CreateServerScreen
from slime.tui.screens.dashboard import DashboardView
from slime.tui.screens.doctor import DoctorScreen
from slime.tui.screens.java import JavaScreen
from slime.tui.screens.server import ServerScreen


def make_server(name: str = "survival", **overrides: object) -> Server:
    values: dict[str, object] = {
        "name": name,
        "project": "paper",
        "minecraft_version": "1.21.4",
        "build": 232,
        "java_major": 21,
        "memory_mb": 2048,
        "port": 25565,
    }
    values.update(overrides)
    return Server(**values)  # type: ignore[arg-type]


def prepare_app(tmp_path: Path) -> SlimeApp:
    app = SlimeApp(Config(tmp_path / "home"))
    app.store.save(make_server())
    return app


async def test_dashboard_shows_saved_servers(tmp_path: Path) -> None:
    app = prepare_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        dashboard = app.screen.query_one(DashboardView)
        table = dashboard.query_one("#servers", DataTable)
        assert table.row_count == 1
        status = str(dashboard.query_one("#dashboard-status", Static).render())
        assert "1 server(s)" in status


async def test_dashboard_empty_state(tmp_path: Path) -> None:
    app = SlimeApp(Config(tmp_path / "home"))

    async with app.run_test() as pilot:
        await pilot.pause()
        dashboard = app.screen.query_one(DashboardView)
        status = str(dashboard.query_one("#dashboard-status", Static).render())
        assert "No servers yet" in status
        assert dashboard.query_one("#servers", DataTable).row_count == 0


async def test_dashboard_new_button_opens_the_wizard(tmp_path: Path) -> None:
    app = prepare_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#new")
        await pilot.pause()
        assert isinstance(app.screen, CreateServerScreen)


async def test_dashboard_open_button_opens_the_selected_server(tmp_path: Path) -> None:
    app = prepare_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#open")
        await pilot.pause()
        assert isinstance(app.screen, ServerScreen)


async def test_dashboard_java_and_doctor_buttons(tmp_path: Path) -> None:
    app = prepare_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#java")
        await pilot.pause()
        assert isinstance(app.screen, JavaScreen)
        app.pop_screen()
        await pilot.pause()

        await pilot.click("#doctor")
        await pilot.pause()
        assert isinstance(app.screen, DoctorScreen)


async def test_dashboard_refresh_button_updates_the_table(tmp_path: Path) -> None:
    app = prepare_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.store.save(make_server("creative"))
        dashboard = app.screen.query_one(DashboardView)
        dashboard.on_button_pressed(
            type("Event", (), {"button": type("Button", (), {"id": "refresh"})()})()
        )
        await pilot.pause()
        assert dashboard.query_one("#servers", DataTable).row_count == 2


async def test_dashboard_stop_button_warns_when_not_running(tmp_path: Path) -> None:
    app = prepare_app(tmp_path)
    notifications: list[str] = []
    app.notify = lambda message, **kwargs: notifications.append(str(message))  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#stop")
        for _ in range(20):
            await pilot.pause()
            if notifications:
                break

    assert any("not running" in message for message in notifications)


async def test_dashboard_stop_button_tolerates_a_slime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slime.errors import ServerError

    app = prepare_app(tmp_path)
    monkeypatch.setattr(app.store, "is_running", lambda name: (True, 999))
    notifications: list[str] = []

    async def fail(name: str) -> None:
        raise ServerError("cannot stop")

    app.notify = lambda message, **kwargs: notifications.append(str(message))  # type: ignore[method-assign]
    monkeypatch.setattr(app, "stop_server", fail)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#stop")
        for _ in range(20):
            await pilot.pause()
            if any("cannot stop" in message for message in notifications):
                break

    assert any("cannot stop" in message for message in notifications)


async def test_dashboard_row_selection_opens_the_server(tmp_path: Path) -> None:
    app = prepare_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        dashboard = app.screen.query_one(DashboardView)
        table = dashboard.query_one("#servers", DataTable)
        table.move_cursor(row=0)
        dashboard.on_data_table_row_selected(
            DataTable.RowSelected(
                table,
                cursor_row=0,
                row_key=table.coordinate_to_cell_key((0, 0)).row_key,
            )
        )
        await pilot.pause()
        assert isinstance(app.screen, ServerScreen)


async def test_dashboard_status_labels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from slime.process import ServerState

    app = prepare_app(tmp_path)
    server = app.store.get("survival")

    class FakeProcess:
        pid = 1234
        state = ServerState.RUNNING
        is_running = True

        def terminate_now(self) -> None:
            return None

    app.processes[server.name] = FakeProcess()  # type: ignore[assignment]

    async with app.run_test() as pilot:
        await pilot.pause()
        dashboard = app.screen.query_one(DashboardView)
        table = dashboard.query_one("#servers", DataTable)
        status = str(table.get_cell_at((0, 7)))
        assert "running" in status


async def test_dashboard_marks_external_servers_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = prepare_app(tmp_path)
    monkeypatch.setattr(app.store, "is_running", lambda name: (True, 4321))

    async with app.run_test() as pilot:
        await pilot.pause()
        dashboard = app.screen.query_one(DashboardView)
        table = dashboard.query_one("#servers", DataTable)
        status = str(table.get_cell_at((0, 7)))
        assert "running" in status
        assert "4321" in status
