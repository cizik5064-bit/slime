"""Tests for console log coloring in the TUI."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button, Input

from slime.config import Config
from slime.models import Server
from slime.tui.app import SlimeApp
from slime.tui.screens.server import ServerScreen, _colorize_log_line, slime_message


@pytest.mark.parametrize(
    "line",
    [
        "[12:36:55 ERROR]: Unable to load the world",
        "java.lang.IllegalStateException: broken",
        "org.bukkit.craftbukkit.v1_12_R1.SomeException: failed",
        "\tat net.minecraft.server.Main.main(Main.java:123)",
        "Caused by: java.io.IOException: nope",
        "Suppressed: java.lang.RuntimeException: hidden",
        "... 12 more",
        'Exception in thread "main" java.lang.NullPointerException',
        "OutOfMemoryError: Java heap space",
    ],
)
def test_exception_lines_are_red(line: str) -> None:
    assert _colorize_log_line(line).style == "red"


def test_info_line_keeps_info_color() -> None:
    assert _colorize_log_line("[12:00:00 INFO]: Ready").style == "white"


def test_plain_line_is_not_colored() -> None:
    assert _colorize_log_line("a normal plugin message").style in (None, "")


def test_slime_prefix_is_bold_bright_green() -> None:
    text = _colorize_log_line(slime_message("Stopping server..."))
    assert text.plain == "[slime] Stopping server..."
    assert text.spans[0].start == 0
    assert text.spans[0].end == len("[slime]")
    assert text.spans[0].style == "bold bright_green"


def test_done_word_is_bright_green() -> None:
    text = _colorize_log_line("[12:00:00 INFO]: Done (1.234s)! For help, type help")
    assert text.style == "white"
    assert any(
        text.plain[span.start : span.end].startswith("Done")
        and span.style == "bold bright_green"
        for span in text.spans
    )


async def test_restart_is_disabled_when_server_is_stopped(tmp_path: Path) -> None:
    app = SlimeApp(Config(tmp_path / "home"))
    server = Server(
        name="survival",
        project="paper",
        minecraft_version="1.21.4",
        build=232,
        java_major=21,
    )
    app.store.save(server)

    async with app.run_test() as pilot:
        app.push_screen(ServerScreen(app, server))
        await pilot.pause()
        assert app.screen.query_one("#restart", Button).disabled is True

async def test_external_server_uses_rcon_for_commands_and_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = SlimeApp(Config(tmp_path / "home"))
    server = Server(
        name="survival",
        project="paper",
        minecraft_version="1.21.4",
        build=232,
        java_major=21,
        port=25565,
    )
    app.store.save(server)
    (app.store.path(server.name) / "server.properties").write_text(
        "enable-rcon=true\nrcon.port=25575\nrcon.password=secret\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(app.store, "is_running", lambda name: (True, 999))
    sent: list[str] = []

    async def fake_send(target: Server, command: str) -> str:
        sent.append(command)
        return "There are 0 players."

    stopped: list[str] = []

    async def fake_stop(name: str) -> None:
        stopped.append(name)

    monkeypatch.setattr(app, "send_remote_command", fake_send)
    monkeypatch.setattr(app, "stop_server", fake_stop)

    async with app.run_test() as pilot:
        app.push_screen(ServerScreen(app, server))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ServerScreen)
        status = screen.query_one("#server-status").render()
        assert "RUNNING" in str(status)
        assert "external" in str(status)
        assert screen.query_one("#toggle", Button).label.plain == "Stop"
        assert screen.query_one("#kill", Button).disabled is True
        assert screen.query_one("#restart", Button).disabled is True

        command_input = screen.query_one("#command", Input)
        command_input.focus()
        command_input.value = "list"
        await pilot.press("enter")
        await pilot.pause()

        await pilot.click("#toggle")
        await pilot.pause()

    assert sent == ["list"]
    assert stopped == ["survival"]


async def test_dashboard_stop_button_stops_the_selected_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = SlimeApp(Config(tmp_path / "home"))
    app.store.save(
        Server(
            name="survival",
            project="paper",
            minecraft_version="1.21.4",
            build=232,
            java_major=21,
        )
    )
    monkeypatch.setattr(app.store, "is_running", lambda name: (True, 999))
    stopped: list[str] = []

    async def fake_stop(name: str) -> None:
        stopped.append(name)

    monkeypatch.setattr(app, "stop_server", fake_stop)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#stop")
        for _ in range(20):
            await pilot.pause()
            if stopped:
                break

    assert stopped == ["survival"]
