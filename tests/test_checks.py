from __future__ import annotations

import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from slime.checks import (
    CheckStatus,
    check_disk,
    check_eula,
    check_home_writable,
    check_jar,
    check_java,
    check_memory,
    check_port,
    check_properties_port,
    has_failures,
    port_available,
    run_checks,
    summarize,
)
from slime.config import Config
from slime.java import JavaManager
from slime.models import JavaInstall, Server
from slime.store import ServerStore


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(tmp_path / "home")


@pytest.fixture
def store(config: Config) -> ServerStore:
    return ServerStore(config)


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


class FakeJavaManager:
    def __init__(self, install: JavaInstall | None = None) -> None:
        self.install = install

    def find_for(self, server: Server) -> JavaInstall | None:
        return self.install

    def installed(self) -> list[JavaInstall]:
        return [self.install] if self.install else []


def test_home_writable(config: Config) -> None:
    result = check_home_writable(config)
    assert result.status is CheckStatus.OK
    assert str(config.paths.home) in result.message


def test_disk_check(config: Config) -> None:
    result = check_disk(config)
    assert result.status in {CheckStatus.OK, CheckStatus.WARN, CheckStatus.FAIL}
    assert result.scope == "global"


def test_disk_check_missing_path(config: Config, tmp_path: Path) -> None:
    result = check_disk(config, path=tmp_path / "missing" / "deep")
    assert result.status is CheckStatus.WARN
    assert result.scope == "server"


def test_port_available_and_busy() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("0.0.0.0", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        assert port_available(port) is False
        server = make_server(port=port)
        result = check_port(server)
        assert result.status is CheckStatus.FAIL

    assert port_available(port) is True


def test_check_port_running_server() -> None:
    result = check_port(make_server(port=25565), running=True)
    assert result.status is CheckStatus.OK
    assert result.scope == "server"


def test_check_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    gib = 1024**3
    memory = SimpleNamespace(total=8 * gib, available=3 * gib)
    monkeypatch.setattr("slime.checks.psutil.virtual_memory", lambda: memory)

    assert check_memory(make_server(memory_mb=2048)).status is CheckStatus.OK
    assert check_memory(make_server(memory_mb=4096)).status is CheckStatus.WARN
    assert check_memory(make_server(memory_mb=8192)).status is CheckStatus.WARN
    assert check_memory(make_server(memory_mb=16384)).status is CheckStatus.FAIL


def test_check_java_missing() -> None:
    result = check_java(make_server(), FakeJavaManager())  # type: ignore[arg-type]
    assert result.status is CheckStatus.FAIL
    assert "slime java install 21" in (result.hint or "")


def test_check_java_wrong_major() -> None:
    install = JavaInstall(major=17, version="17.0.1", path="/java", home="/java")
    result = check_java(make_server(), FakeJavaManager(install))  # type: ignore[arg-type]
    assert result.status is CheckStatus.FAIL
    assert "Java 17 found" in result.message


def test_check_java_ok() -> None:
    install = JavaInstall(major=21, version="21.0.1", path="/java", home="/java")
    result = check_java(make_server(), FakeJavaManager(install))  # type: ignore[arg-type]
    assert result.status is CheckStatus.OK


def test_check_jar_missing_and_present(store: ServerStore) -> None:
    server = make_server()
    assert check_jar(server, store).status is CheckStatus.FAIL
    (store.path(server.name) / server.jar_file).parent.mkdir(parents=True)
    (store.path(server.name) / server.jar_file).write_bytes(b"x" * 2048)
    assert check_jar(server, store).status is CheckStatus.OK


def test_check_eula(store: ServerStore) -> None:
    server = make_server()
    store.save(server)
    assert check_eula(server, store).status is CheckStatus.FAIL

    server.eula_accepted = True
    (store.path(server.name) / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    assert check_eula(server, store).status is CheckStatus.OK

    proxy = make_server("proxy", project="velocity")
    assert check_eula(proxy, store).status is CheckStatus.INFO


def test_check_properties_port(store: ServerStore) -> None:
    server = make_server()
    path = store.path(server.name) / "server.properties"
    path.parent.mkdir(parents=True)

    assert check_properties_port(server, store).status is CheckStatus.WARN

    path.write_text("server-port=25565\n", encoding="utf-8")
    assert check_properties_port(server, store).status is CheckStatus.OK

    path.write_text("server-port=25566\n", encoding="utf-8")
    result = check_properties_port(server, store)
    assert result.status is CheckStatus.WARN
    assert "25566" in result.message

    proxy = make_server("proxy", project="velocity")
    assert check_properties_port(proxy, store).status is CheckStatus.INFO


def test_run_checks_global(config: Config, store: ServerStore) -> None:
    manager = JavaManager(config)
    results = run_checks(config, store, manager)
    ids = {result.id for result in results}
    assert {"python", "os", "home", "disk", "servers", "java"} <= ids
    assert not has_failures(results)


def test_run_checks_for_server(config: Config, store: ServerStore) -> None:
    server = make_server()
    store.save(server)
    manager = JavaManager(config)
    results = run_checks(config, store, manager, server=server)
    ids = {result.id for result in results}
    assert {"jar", "java", "eula", "properties", "port", "memory", "disk"} <= ids
    assert all(result.scope == "server" for result in results[4:])
    assert has_failures(results)


def test_summarize() -> None:
    from slime.checks import CheckResult

    results = [
        CheckResult("a", "A", CheckStatus.OK, ""),
        CheckResult("b", "B", CheckStatus.OK, ""),
        CheckResult("c", "C", CheckStatus.FAIL, ""),
    ]
    counts = summarize(results)
    assert counts[CheckStatus.OK] == 2
    assert counts[CheckStatus.FAIL] == 1
    assert counts[CheckStatus.WARN] == 0
    assert has_failures(results) is True
