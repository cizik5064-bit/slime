"""Headless tests for the create-server wizard."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Input, Select, Static, Switch

from slime.config import Config
from slime.errors import SlimeError
from slime.models import Server
from slime.provision import CreateRequest
from slime.tui.app import SlimeApp
from slime.tui.screens.create import CreateServerScreen


def make_server(name: str = "survival") -> Server:
    return Server(
        name=name,
        project="paper",
        minecraft_version="1.21.4",
        build=232,
        java_major=21,
        memory_mb=2048,
        port=25565,
    )


class FakeProvisioner:
    def __init__(self) -> None:
        self.requests: list[CreateRequest] = []
        self.result = make_server()

    def create(self, request: CreateRequest, *, progress=None) -> Server:
        self.requests.append(request)
        if progress is not None:
            progress("Downloading server jar", 1, 2)
            progress("Server created", 1, 1)
        return self.result


def prepare_app(tmp_path: Path) -> tuple[SlimeApp, FakeProvisioner]:
    app = SlimeApp(Config(tmp_path / "home"))
    provisioner = FakeProvisioner()
    app.provisioner = provisioner  # type: ignore[assignment]
    app.papermc.versions = lambda project: ["1.21.4", "1.20.6"]  # type: ignore[method-assign]
    return app, provisioner


async def wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition was not met in time")
        await asyncio.sleep(0.02)


async def test_create_screen_provisions_a_server(tmp_path: Path) -> None:
    app, provisioner = prepare_app(tmp_path)
    results: list[Server | None] = []

    async with app.run_test() as pilot:
        app.push_screen(CreateServerScreen(app), results.append)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CreateServerScreen)

        screen.query_one("#name", Input).value = "survival"
        screen.query_one("#version", Input).value = "1.21.4"
        screen.query_one("#memory", Input).value = "4096"
        screen.query_one("#port", Input).value = "25570"
        screen.query_one("#build", Input).value = "42"
        screen.query_one("#channel", Select).value = "BETA"
        screen.query_one("#eula", Switch).value = True

        screen.create_server()
        await wait_for(lambda: bool(results))

    assert results == [provisioner.result]
    request = provisioner.requests[0]
    assert request.name == "survival"
    assert request.version == "1.21.4"
    assert request.memory_mb == 4096
    assert request.port == 25570
    assert request.build == 42
    assert request.channel == "BETA"
    assert request.accept_eula is True


async def test_create_screen_reports_invalid_numbers(tmp_path: Path) -> None:
    app, provisioner = prepare_app(tmp_path)

    async with app.run_test() as pilot:
        app.push_screen(CreateServerScreen(app))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CreateServerScreen)

        screen.query_one("#name", Input).value = "survival"
        screen.query_one("#memory", Input).value = "not-a-number"
        screen.create_server()
        await pilot.pause()

        status = screen.query_one("#create-status", Static).render()
        assert "invalid literal" in str(status)
        assert provisioner.requests == []


async def test_create_screen_handles_version_failure_and_proxies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _ = prepare_app(tmp_path)

    def fail_versions(project: str) -> list[str]:
        raise SlimeError("offline")

    monkeypatch.setattr(app.papermc, "versions", fail_versions)

    async with app.run_test() as pilot:
        app.push_screen(CreateServerScreen(app))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CreateServerScreen)

        await wait_for(
            lambda: "Could not load versions" in str(screen.query_one("#create-status").render())
        )
        select = screen.query_one("#project", Select)
        select.value = "velocity"
        await pilot.pause()

        assert screen.query_one("#eula", Switch).disabled is True
        assert screen.query_one("#java", Select).value == "auto"
        assert "Java 17" in str(screen.query_one("#java-hint", Static).render())


async def test_create_screen_cancel_dismisses_without_creating(tmp_path: Path) -> None:
    app, provisioner = prepare_app(tmp_path)
    results: list[Server | None] = []

    async with app.run_test() as pilot:
        app.push_screen(CreateServerScreen(app), results.append)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CreateServerScreen)
        screen.action_cancel()
        await pilot.pause()

    assert results == [None]
    assert provisioner.requests == []

