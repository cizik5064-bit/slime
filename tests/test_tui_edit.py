"""Headless tests for the server edit screen."""

from __future__ import annotations

from pathlib import Path

from textual.widgets import Input, TextArea

from slime.config import Config
from slime.models import AIKAR_FLAGS, Server
from slime.properties import ensure_server_properties
from slime.tui.app import SlimeApp
from slime.tui.screens.edit import EditServerScreen


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


async def test_edit_screen_saves_general_settings(tmp_path: Path) -> None:
    config = Config(tmp_path / "home")
    app = SlimeApp(config)
    server = make_server()
    app.store.save(server)
    ensure_server_properties(
        app.store.path(server.name) / "server.properties",
        port=server.port,
    )

    async with app.run_test() as pilot:
        app.push_screen(EditServerScreen(app, server))
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, EditServerScreen)
        screen.query_one("#edit-name", Input).value = "creative"
        screen.query_one("#edit-min-memory", Input).value = "1024"
        screen.query_one("#edit-max-memory", Input).value = "4096"
        screen.query_one("#edit-cpu-cores", Input).value = "2"
        screen.query_one("#edit-flags", TextArea).load_text("-Dfoo=bar")

        property_inputs = [
            widget
            for widget in screen.query(Input)
            if widget.has_class("property-value")
        ]
        port_index = screen._property_keys.index("server-port")
        property_inputs[port_index].value = "25566"

        await pilot.click("#edit-save")
        await pilot.pause()

    saved = app.store.get("creative")
    assert saved.min_memory_mb == 1024
    assert saved.memory_mb == 4096
    assert saved.cpu_cores == 2
    assert saved.extra_args == ["-Dfoo=bar"]
    assert saved.port == 25566
    assert (app.store.path("creative") / "server.properties").is_file()


async def test_edit_screen_uses_aikar_flags_by_default(tmp_path: Path) -> None:
    config = Config(tmp_path / "home")
    app = SlimeApp(config)
    server = make_server()
    app.store.save(server)
    ensure_server_properties(
        app.store.path(server.name) / "server.properties",
        port=server.port,
    )

    async with app.run_test() as pilot:
        app.push_screen(EditServerScreen(app, server))
        await pilot.pause()
        flags = app.screen.query_one("#edit-flags", TextArea).text.split()
        assert flags == list(AIKAR_FLAGS)


async def test_edit_screen_deletes_after_confirmation(tmp_path: Path) -> None:
    config = Config(tmp_path / "home")
    app = SlimeApp(config)
    server = make_server()
    app.store.save(server)

    async with app.run_test() as pilot:
        app.push_screen(EditServerScreen(app, server))
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, EditServerScreen)
        screen.confirm_delete()
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()

        assert not app.store.exists("survival")
