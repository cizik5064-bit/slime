"""Tests for the hold-Enter confirmation modal."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from slime.config import Config
from slime.tui.app import SlimeApp
from slime.tui.screens import confirm as confirm_module
from slime.tui.screens.confirm import HoldConfirmScreen


async def test_hold_enter_confirms_after_the_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(confirm_module, "HOLD_SECONDS", 0.2)
    app = SlimeApp(Config(tmp_path / "home"))
    results: list[bool] = []

    async with app.run_test() as pilot:
        app.push_screen(HoldConfirmScreen("Dangerous action"), results.append)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, HoldConfirmScreen)

        screen._enter_pressed()
        await asyncio.sleep(0.3)
        await pilot.pause()

    assert results == [True]


async def test_cancel_returns_false(tmp_path: Path) -> None:
    app = SlimeApp(Config(tmp_path / "home"))
    results: list[bool] = []

    async with app.run_test() as pilot:
        app.push_screen(HoldConfirmScreen("Dangerous action"), results.append)
        await pilot.pause()
        await pilot.click("#hold-cancel")
        await pilot.pause()

    assert results == [False]
