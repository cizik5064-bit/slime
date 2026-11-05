"""Build a standalone Slime executable with Nuitka.

Usage::

    python -m pip install -e ".[build]"
    python scripts/build_exe.py

The resulting binary is written to ``dist/`` together with a versioned copy and
a SHA-256 checksum. On Windows the file is ``slime.exe``; on Linux and macOS it
is ``slime``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts" / "slime_entry.py"
DIST = ROOT / "dist"
CSS_FILE = ROOT / "src" / "slime" / "tui" / "app.tcss"

sys.path.insert(0, str(ROOT / "src"))
from slime import __version__  # noqa: E402


def platform_tag() -> str:
    system = platform.system().lower()
    os_name = {"windows": "windows", "darwin": "macos"}.get(system, system or "unknown")
    machine = platform.machine().lower()
    arch = {
        "amd64": "x64",
        "x86_64": "x64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine, machine or "unknown")
    return f"{os_name}-{arch}"


def numeric_version(version: str) -> str:
    parts = [part for part in version.split(".") if part.isdigit()]
    while len(parts) < 4:
        parts.append("0")
    return ".".join(parts[:4])


def main() -> int:
    if importlib.util.find_spec("nuitka") is None:
        print(
            'Nuitka is not installed. Run: pip install -e ".[build]"',
            file=sys.stderr,
        )
        return 1

    if not CSS_FILE.is_file():
        print(f"Missing TUI stylesheet: {CSS_FILE}", file=sys.stderr)
        return 1

    DIST.mkdir(parents=True, exist_ok=True)
    executable_name = "slime.exe" if os.name == "nt" else "slime"
    tag = platform_tag()
    versioned_name = f"slime-{__version__}-{tag}{Path(executable_name).suffix}"

    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--onefile",
        "--standalone",
        "--assume-yes-for-downloads",
        "--follow-imports",
        "--include-package=slime",
        "--include-package=textual",
        "--include-package=py7zr",
        "--include-package-data=slime",
        f"--output-dir={DIST}",
        f"--output-filename={executable_name}",
        "--remove-output",
        str(ENTRY),
    ]

    if os.name == "nt":
        version = numeric_version(__version__)
        command += [
            # Avoid the legacy Dependency Walker download, which relies on an
            # external site and fails when it is unavailable. Nuitka's pefile
            # scanner is bundled and works offline.
            "--experimental=force-dependencies-pefile",
            "--windows-console-mode=force",
            f"--file-version={version}",
            f"--product-version={version}",
            "--file-description=Slime Minecraft server manager",
            "--product-name=Slime",
            "--company-name=Slime contributors",
            "--copyright=MIT License",
        ]

    env = os.environ.copy()
    python_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(ROOT / "src") + (os.pathsep + python_path if python_path else "")
    )

    print("Running:", subprocess.list2cmdline(command), flush=True)
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if completed.returncode != 0:
        return completed.returncode

    built = DIST / executable_name
    if not built.is_file():
        print(f"Nuitka finished but {built} was not created.", file=sys.stderr)
        return 1

    versioned = DIST / versioned_name
    shutil.copy2(built, versioned)

    checksum = hashlib.sha256(versioned.read_bytes()).hexdigest()
    (versioned.with_name(versioned.name + ".sha256")).write_text(
        f"{checksum}  {versioned.name}\n", encoding="utf-8"
    )

    print(f"\nBuilt: {built}")
    print(f"Release asset: {versioned}")
    print(f"SHA-256: {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
