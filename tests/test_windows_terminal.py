"""Tests for the Windows Terminal relaunch helper."""

from __future__ import annotations

import sys

import pytest

from slime import windows_terminal as wt


def make_interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend the current stdout/stdin are real terminals.

    Pytest replaces ``sys.stdout`` after fixture setup, so this has to be
    called from inside the test body.
    """
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)


def test_non_windows_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wt, "is_windows", lambda: False)
    assert wt.relaunch_in_windows_terminal() is False


def test_already_in_windows_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    make_interactive(monkeypatch)
    monkeypatch.setattr(wt, "is_windows", lambda: True)
    monkeypatch.setenv("WT_SESSION", "session-id")
    assert wt.relaunch_in_windows_terminal() is False


def test_opt_out_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    make_interactive(monkeypatch)
    monkeypatch.setattr(wt, "is_windows", lambda: True)
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.setenv(wt.DISABLE_ENV, "1")
    assert wt.relaunch_in_windows_terminal() is False


def test_relaunch_command_for_python_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["slime"])
    assert wt.relaunch_command() == [sys.executable, "-m", "slime", "tui"]


def test_relaunch_in_windows_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    make_interactive(monkeypatch)
    monkeypatch.setattr(wt, "is_windows", lambda: True)
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.delenv(wt.WT_RELAUNCH_ENV, raising=False)
    monkeypatch.setattr(wt, "find_windows_terminal", lambda: r"C:\Windows\wt.exe")
    monkeypatch.setattr(sys, "argv", ["slime", "tui"])

    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_popen(command: list[str], **kwargs: object) -> object:
        calls.append((command, kwargs["env"]))  # type: ignore[arg-type]
        return object()

    monkeypatch.setattr(wt.subprocess, "Popen", fake_popen)

    assert sys.stdout.isatty() is True
    assert sys.stdin.isatty() is True
    assert wt.relaunch_in_windows_terminal() is True
    command, environment = calls[0]
    assert command[:5] == [
        r"C:\Windows\wt.exe",
        "new-tab",
        "--title",
        "Slime",
        "--",
    ]
    assert command[-3:] == ["-m", "slime", "tui"]
    assert environment[wt.WT_RELAUNCH_ENV] == "1"


def test_installs_windows_terminal_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    make_interactive(monkeypatch)
    monkeypatch.setattr(wt, "is_windows", lambda: True)
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.delenv(wt.WT_RELAUNCH_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", ["slime"])

    found = iter([None, r"C:\Windows\wt.exe"])
    monkeypatch.setattr(wt, "find_windows_terminal", lambda: next(found))
    installs: list[bool] = []
    monkeypatch.setattr(wt, "install_windows_terminal", lambda: installs.append(True) or True)

    class FakePopen:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    monkeypatch.setattr(wt.subprocess, "Popen", FakePopen)

    assert wt.relaunch_in_windows_terminal() is True
    assert installs == [True]


def test_continues_when_install_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    make_interactive(monkeypatch)
    monkeypatch.setattr(wt, "is_windows", lambda: True)
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.delenv(wt.WT_RELAUNCH_ENV, raising=False)
    monkeypatch.setattr(wt, "find_windows_terminal", lambda: None)
    monkeypatch.setattr(wt, "install_windows_terminal", lambda: False)
    assert wt.relaunch_in_windows_terminal() is False
