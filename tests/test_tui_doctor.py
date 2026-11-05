"""Headless tests for the environment diagnostics screen."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import DataTable, Static

from slime.checks import CheckResult, CheckStatus
from slime.config import Config
from slime.tui import screens
from slime.tui.app import SlimeApp
from slime.tui.screens.doctor import DoctorScreen


def sample_results() -> list[CheckResult]:
    return [
        CheckResult("python", "Python", CheckStatus.OK, "3.14"),
        CheckResult("os", "Operating system", CheckStatus.INFO, "Windows 11"),
        CheckResult("disk", "Disk space", CheckStatus.WARN, "Low", hint="Free space"),
        CheckResult("eula", "EULA", CheckStatus.FAIL, "Missing", hint="Accept it"),
    ]


async def wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition was not met in time")
        await asyncio.sleep(0.02)


async def test_doctor_screen_shows_checks_and_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = SlimeApp(Config(tmp_path / "home"))
    calls: list[str] = []

    def fake_run_checks(*_args: object, **_kwargs: object) -> list[CheckResult]:
        calls.append("run")
        return sample_results()

    monkeypatch.setattr(screens.doctor, "run_checks", fake_run_checks)

    async with app.run_test() as pilot:
        app.push_screen(DoctorScreen(app))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DoctorScreen)

        await wait_for(
            lambda: "1 ok" in str(screen.query_one("#doctor-summary", Static).render())
        )
        table = screen.query_one("#checks-table", DataTable)
        assert table.row_count == 4
        summary = str(screen.query_one("#doctor-summary", Static).render())
        assert "1 info" in summary
        assert "1 warning(s)" in summary
        assert "1 error(s)" in summary

        screen.action_refresh()
        await wait_for(lambda: len(calls) == 2)


async def test_doctor_screen_run_again_button_and_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = SlimeApp(Config(tmp_path / "home"))
    calls: list[str] = []

    def fake_run_checks(*_args: object, **_kwargs: object) -> list[CheckResult]:
        calls.append("run")
        return sample_results()

    monkeypatch.setattr(screens.doctor, "run_checks", fake_run_checks)

    async with app.run_test() as pilot:
        app.push_screen(DoctorScreen(app))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DoctorScreen)
        await wait_for(lambda: bool(calls))

        screen.on_button_pressed(
            type("Event", (), {"button": type("Button", (), {"id": "refresh"})()})()
        )
        await wait_for(lambda: len(calls) == 2)

        screen.action_back()
        await pilot.pause()
        assert not isinstance(app.screen, DoctorScreen)


async def test_doctor_screen_reports_an_unexpected_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = SlimeApp(Config(tmp_path / "home"))

    def explode(*_args: object, **_kwargs: object) -> list[CheckResult]:
        raise RuntimeError("boom")

    monkeypatch.setattr(screens.doctor, "run_checks", explode)

    async with app.run_test() as pilot:
        app.push_screen(DoctorScreen(app))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DoctorScreen)
        await wait_for(
            lambda: "boom" in str(screen.query_one("#doctor-summary", Static).render())
        )
