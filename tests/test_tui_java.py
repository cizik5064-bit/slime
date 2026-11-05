"""Headless tests for the Java runtime manager screen."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import DataTable, Select, Static

from slime.config import Config
from slime.errors import JavaError
from slime.models import JavaInstall
from slime.tui.app import SlimeApp
from slime.tui.screens.java import FALLBACK_RELEASES, JavaScreen


def make_install(major: int = 21) -> JavaInstall:
    return JavaInstall(
        major=major,
        version="21.0.5+11",
        path=f"C:/java/{major}/bin/java.exe",
        home=f"C:/java/{major}",
        os="windows",
        arch="x64",
    )


class FakeClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def releases(self) -> list[int]:
        if self.fail:
            raise JavaError("offline")
        return [17, 21, 25]

    def lts_releases(self) -> list[int]:
        return [21, 25]

    def close(self) -> None:
        return None


class FakeJavaManager:
    def __init__(self) -> None:
        self.runtimes: list[JavaInstall] = [make_install(21)]
        self.system = make_install(17)
        self.client = FakeClient()
        self.installed_majors: list[int] = []
        self.install_error: Exception | None = None

    def installed(self) -> list[JavaInstall]:
        return list(self.runtimes)

    def system_java(self) -> JavaInstall | None:
        return self.system

    def install(self, major: int, *, progress=None) -> JavaInstall:
        if self.install_error is not None:
            raise self.install_error
        if progress is not None:
            progress(50, 100)
            progress(0, None)
        self.installed_majors.append(major)
        return make_install(major)

    def remove(self, major: int) -> bool:
        self.runtimes = [item for item in self.runtimes if item.major != major]
        return True


def prepare_app(tmp_path: Path) -> tuple[SlimeApp, FakeJavaManager]:
    app = SlimeApp(Config(tmp_path / "home"))
    manager = FakeJavaManager()
    app.java_manager = manager  # type: ignore[assignment]
    return app, manager


async def wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition was not met in time")
        await asyncio.sleep(0.02)


async def test_java_screen_lists_managed_and_system_runtimes(tmp_path: Path) -> None:
    app, _manager = prepare_app(tmp_path)

    async with app.run_test() as pilot:
        app.push_screen(JavaScreen(app))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, JavaScreen)

        table = screen.query_one("#java-table", DataTable)
        assert table.row_count == 2
        status = str(screen.query_one("#java-status", Static).render())
        assert "1 runtime(s) managed by Slime" in status

        select = screen.query_one("#java-major", Select)
        await wait_for(lambda: select.value == "21")
        assert "Java 25" in str(select._options)


async def test_java_screen_without_managed_runtimes(tmp_path: Path) -> None:
    app, manager = prepare_app(tmp_path)
    manager.runtimes = []
    manager.system = None

    async with app.run_test() as pilot:
        app.push_screen(JavaScreen(app))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, JavaScreen)
        status = str(screen.query_one("#java-status", Static).render())
        assert "No managed runtimes yet" in status


async def test_java_screen_falls_back_when_adoptium_fails(tmp_path: Path) -> None:
    app, manager = prepare_app(tmp_path)
    manager.client = FakeClient(fail=True)

    async with app.run_test() as pilot:
        app.push_screen(JavaScreen(app))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, JavaScreen)

        await wait_for(
            lambda: "Adoptium unavailable"
            in str(screen.query_one("#java-status", Static).render())
        )
        select = screen.query_one("#java-major", Select)
        assert select.value == "21"
        assert str(len(FALLBACK_RELEASES)) in str(len(select._options))


async def test_java_screen_installs_the_selected_major(tmp_path: Path) -> None:
    app, manager = prepare_app(tmp_path)

    async with app.run_test() as pilot:
        app.push_screen(JavaScreen(app))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, JavaScreen)
        screen.query_one("#java-major", Select).value = "25"

        screen.action_refresh()
        await pilot.pause()
        screen.query_one("#java-major", Select).value = "25"
        screen.install_selected()
        await wait_for(lambda: manager.installed_majors == [25])
        await pilot.pause()

        assert manager.installed_majors == [25]
        assert screen.query_one("#java-table", DataTable).row_count == 2


async def test_java_screen_reports_install_failure(tmp_path: Path) -> None:
    app, manager = prepare_app(tmp_path)
    manager.install_error = JavaError("download failed")

    async with app.run_test() as pilot:
        app.push_screen(JavaScreen(app))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, JavaScreen)
        screen.query_one("#java-major", Select).value = "21"
        screen.install_selected()
        await wait_for(
            lambda: "Install failed"
            in str(screen.query_one("#java-status", Static).render())
        )


async def test_java_screen_removes_the_selected_runtime(tmp_path: Path) -> None:
    app, manager = prepare_app(tmp_path)

    async with app.run_test() as pilot:
        app.push_screen(JavaScreen(app))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, JavaScreen)
        table = screen.query_one("#java-table", DataTable)
        table.move_cursor(row=0)
        screen.confirm_remove()
        await pilot.pause()

        from slime.tui.screens.confirm import ConfirmScreen

        confirm = app.screen
        assert isinstance(confirm, ConfirmScreen)
        confirm.dismiss(True)
        await pilot.pause()

        assert manager.runtimes == []
        assert table.row_count == 1  # system Java remains


async def test_java_screen_remove_requires_a_managed_selection(tmp_path: Path) -> None:
    app, manager = prepare_app(tmp_path)
    manager.runtimes = []
    manager.system = make_install(17)

    async with app.run_test() as pilot:
        app.push_screen(JavaScreen(app))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, JavaScreen)
        table = screen.query_one("#java-table", DataTable)
        table.move_cursor(row=0)
        screen.confirm_remove()
        await pilot.pause()
        assert isinstance(app.screen, JavaScreen)


async def test_java_screen_buttons_navigate(tmp_path: Path) -> None:
    app, _ = prepare_app(tmp_path)

    async with app.run_test() as pilot:
        app.push_screen(JavaScreen(app))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, JavaScreen)
        screen.action_back()
        await pilot.pause()
        assert not isinstance(app.screen, JavaScreen)

    assert JavaScreen.platform_label()
