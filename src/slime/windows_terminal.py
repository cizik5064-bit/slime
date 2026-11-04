"""Relaunch the interactive TUI inside Windows Terminal.

The classic Windows console host (``conhost``, used by ``cmd.exe`` and older
PowerShell windows) does not render the Unicode box-drawing characters used by
Textual reliably. When Slime is started from such a console, it re-opens itself
in Windows Terminal. If Windows Terminal is missing, Slime tries to install it
with winget first.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

WT_RELAUNCH_ENV = "SLIME_WT_RELAUNCHED"
DISABLE_ENV = "SLIME_NO_WINDOWS_TERMINAL"
WINGET_PACKAGE = "Microsoft.WindowsTerminal"


def is_windows() -> bool:
    return os.name == "nt"


def in_windows_terminal() -> bool:
    """Return ``True`` when the current process already runs in Windows Terminal."""
    return bool(os.environ.get("WT_SESSION"))


def find_windows_terminal() -> str | None:
    """Locate ``wt.exe`` even when it is not on ``PATH`` yet."""
    for name in ("wt.exe", "wt"):
        found = shutil.which(name)
        if found:
            return found
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = Path(local_app_data) / "Microsoft" / "WindowsApps" / "wt.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def install_windows_terminal() -> bool:
    """Install Windows Terminal with winget. Returns ``True`` on success."""
    winget = shutil.which("winget.exe") or shutil.which("winget")
    if not winget:
        return False
    print(
        "Slime: Windows Terminal was not found. Installing it with winget…",
        file=sys.stderr,
        flush=True,
    )
    try:
        completed = subprocess.run(
            [
                winget,
                "install",
                "--id",
                WINGET_PACKAGE,
                "--exact",
                "--silent",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ],
            check=False,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def relaunch_command() -> list[str]:
    """Build the command that reopens Slime in the TUI."""
    arguments = sys.argv[1:]
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return [sys.executable, *(arguments or ["tui"])]
    return [sys.executable, "-m", "slime", *(arguments or ["tui"])]


def relaunch_in_windows_terminal() -> bool:
    """Reopen the current TUI command in Windows Terminal when needed.

    Returns ``True`` when a new Windows Terminal process was started and the
    caller should exit. Returns ``False`` when the current process should keep
    running in the existing console.
    """
    if not is_windows():
        return False
    if not sys.stdout.isatty() or not sys.stdin.isatty():
        return False
    if os.environ.get(DISABLE_ENV):
        return False
    if in_windows_terminal() or os.environ.get(WT_RELAUNCH_ENV):
        return False

    wt = find_windows_terminal()
    if wt is None:
        if not install_windows_terminal():
            print(
                "Slime: could not install Windows Terminal; continuing in the "
                "current console.",
                file=sys.stderr,
                flush=True,
            )
            return False
        wt = find_windows_terminal()
        if wt is None:
            print(
                "Slime: Windows Terminal is still unavailable; continuing in the "
                "current console.",
                file=sys.stderr,
                flush=True,
            )
            return False

    command = [
        wt,
        "new-tab",
        "--title",
        "Slime",
        "--",
        *relaunch_command(),
    ]
    environment = os.environ.copy()
    environment[WT_RELAUNCH_ENV] = "1"
    try:
        subprocess.Popen(
            command,
            env=environment,
            close_fds=True,
        )
    except OSError:
        return False
    return True


__all__ = [
    "DISABLE_ENV",
    "WT_RELAUNCH_ENV",
    "find_windows_terminal",
    "in_windows_terminal",
    "install_windows_terminal",
    "is_windows",
    "relaunch_command",
    "relaunch_in_windows_terminal",
]
