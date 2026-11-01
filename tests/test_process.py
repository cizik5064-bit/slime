from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from slime.errors import ServerError
from slime.models import Server
from slime.process import ServerProcess, ServerState


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


def make_process(
    tmp_path: Path,
    *,
    server: Server | None = None,
    script: str | None = None,
) -> ServerProcess:
    server = server or make_server()
    command_override = None
    if script is not None:
        script_path = tmp_path / "fake_server.py"
        script_path.write_text(script, encoding="utf-8")
        command_override = [sys.executable, "-u", str(script_path)]
    return ServerProcess(
        server,
        tmp_path / "server",
        tmp_path / "java",
        log_dir=tmp_path / "logs",
        command_override=command_override,
    )


async def wait_for_state(
    process: ServerProcess, state: ServerState, timeout: float = 10.0
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while process.state is not state:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"state did not become {state}, got {process.state}")
        await asyncio.sleep(0.02)


async def wait_for_line(process: ServerProcess, text: str, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not any(text in line for line in process.lines):
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"line {text!r} not seen in {process.lines}")
        await asyncio.sleep(0.02)


def test_build_command_for_server() -> None:
    process = ServerProcess(
        make_server(extra_args=["-Dfoo=bar"]),
        Path("server"),
        Path("java"),
        log_dir=Path("logs"),
    )
    command = process.build_command()
    assert command[0] == "java"
    assert "-Xms2048M" in command
    assert "-Xmx2048M" in command
    assert "--nogui" in command
    assert command[-1] == "-Dfoo=bar"
    assert process.pid is None
    assert process.state is ServerState.STOPPED
    assert process.is_running is False


def test_build_command_for_proxy() -> None:
    process = ServerProcess(
        make_server(project="velocity"),
        Path("server"),
        Path("java"),
        log_dir=Path("logs"),
    )
    assert "--nogui" not in process.build_command()


def test_command_override() -> None:
    process = ServerProcess(
        make_server(),
        Path("server"),
        Path("java"),
        log_dir=Path("logs"),
        command_override=["echo", "hello"],
    )
    assert process.build_command() == ["echo", "hello"]


async def test_start_missing_java(tmp_path: Path) -> None:
    process = make_process(tmp_path)
    with pytest.raises(ServerError, match="Java executable not found"):
        await process.start()


async def test_start_missing_jar(tmp_path: Path) -> None:
    process = make_process(tmp_path)
    process.java_path.parent.mkdir(parents=True, exist_ok=True)
    process.java_path.write_text("", encoding="utf-8")
    with pytest.raises(ServerError, match="Server jar not found"):
        await process.start()


async def test_start_send_stop_and_log(tmp_path: Path) -> None:
    script = (
        "import sys\n"
        "print('Done (1.0s)! For help, type help', flush=True)\n"
        "for line in sys.stdin:\n"
        "    print('got: ' + line.strip(), flush=True)\n"
        "    if line.strip() == 'stop':\n"
        "        break\n"
    )
    process = make_process(tmp_path, script=script)
    states: list[ServerState] = []
    lines: list[str] = []
    process.add_state_listener(states.append)
    process.add_line_listener(lines.append)

    await process.start()
    await wait_for_state(process, ServerState.RUNNING)
    assert process.is_running is True
    assert process.pid is not None
    assert process.started_at is not None
    assert (process.server_dir / "slime.pid").is_file()

    await process.send("say hi")
    await wait_for_line(process, "got: say hi")

    await process.stop(timeout=5)
    await wait_for_state(process, ServerState.STOPPED)
    assert process.exit_code == 0
    assert not (process.server_dir / "slime.pid").exists()
    assert ServerState.STARTING in states
    assert ServerState.RUNNING in states
    assert ServerState.STOPPING in states
    assert ServerState.STOPPED in states
    assert any("Done (" in line for line in lines)

    log_path = tmp_path / "logs" / "survival.log"
    assert log_path.is_file()
    assert "starting survival" in log_path.read_text(encoding="utf-8")
    assert "got: say hi" in log_path.read_text(encoding="utf-8")


async def test_crash_sets_crashed_state(tmp_path: Path) -> None:
    script = "import sys\nprint('boom', flush=True)\nsys.exit(3)\n"
    process = make_process(tmp_path, script=script)
    await process.start()
    await wait_for_state(process, ServerState.CRASHED)
    assert process.exit_code == 3


async def test_send_when_not_running(tmp_path: Path) -> None:
    process = make_process(tmp_path)
    with pytest.raises(ServerError, match="not running"):
        await process.send("stop")


async def test_stop_when_not_running(tmp_path: Path) -> None:
    process = make_process(tmp_path)
    await process.stop()
    assert process.state is ServerState.STOPPED
    assert process.exit_code is None


async def test_second_start_rejected(tmp_path: Path) -> None:
    script = "import sys\nfor line in sys.stdin:\n    break\n"
    process = make_process(tmp_path, script=script)
    await process.start()
    with pytest.raises(ServerError, match="already running"):
        await process.start()
    await process.stop(timeout=5)


async def test_uptime_and_remove_listener(tmp_path: Path) -> None:
    process = make_process(tmp_path)
    assert process.uptime() == 0.0
    listener = lambda line: None  # noqa: E731
    process.add_line_listener(listener)
    process.add_line_listener(listener)
    assert process._line_listeners == [listener]
    process.remove_line_listener(listener)
    assert process._line_listeners == []
    process.remove_line_listener(listener)


def test_terminate_now_without_process(tmp_path: Path) -> None:
    process = make_process(tmp_path)
    process.terminate_now()
