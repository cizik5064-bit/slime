from __future__ import annotations

import json
from pathlib import Path

import pytest

from slime.config import Config
from slime.errors import ServerError, ValidationError
from slime.models import Server
from slime.store import METADATA_FILE, PID_FILE, ServerStore


def make_server(name: str = "survival", **overrides: object) -> Server:
    values: dict[str, object] = {
        "name": name,
        "project": "paper",
        "minecraft_version": "1.21.4",
        "build": 232,
        "java_major": 21,
        "memory_mb": 4096,
        "port": 25565,
    }
    values.update(overrides)
    return Server(**values)  # type: ignore[arg-type]


@pytest.fixture
def store(tmp_path: Path) -> ServerStore:
    config = Config(tmp_path / "home")
    return ServerStore(config)


def test_empty_store(store: ServerStore) -> None:
    assert store.list() == []
    assert store.exists("survival") is False


def test_save_get_list_and_delete(store: ServerStore) -> None:
    server = make_server()
    store.save(server)

    assert store.exists("survival") is True
    assert store.get("survival") == server
    assert store.list() == [server]

    metadata = store.metadata_path("survival")
    assert json.loads(metadata.read_text(encoding="utf-8"))["name"] == "survival"

    store.delete("survival")
    assert not store.path("survival").exists()
    with pytest.raises(ServerError, match="does not exist"):
        store.get("survival")


def test_delete_keep_files(store: ServerStore) -> None:
    server = make_server()
    store.save(server)
    world = store.path("survival") / "world"
    world.mkdir()
    store.write_pid("survival", 1234)

    store.delete("survival", keep_files=True)

    assert store.path("survival").is_dir()
    assert not store.metadata_path("survival").exists()
    assert not store.pid_path("survival").exists()
    assert world.is_dir()


def test_list_skips_broken_records(store: ServerStore) -> None:
    store.save(make_server("good"))
    broken = store.path("broken")
    broken.mkdir(parents=True)
    (broken / METADATA_FILE).write_text("{not json", encoding="utf-8")
    (store.root / "no-metadata").mkdir()

    assert [server.name for server in store.list()] == ["good"]


def test_create_directory_rejects_non_empty(store: ServerStore) -> None:
    path = store.path("survival")
    path.mkdir(parents=True)
    (path / "world").mkdir()

    with pytest.raises(ServerError, match="not empty"):
        store.create_directory("survival")


def test_create_directory_allows_empty_existing(store: ServerStore) -> None:
    path = store.path("survival")
    path.mkdir(parents=True)
    assert store.create_directory("survival") == path


def test_create_directory_rejects_file(store: ServerStore) -> None:
    path = store.path("survival")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ServerError, match="not a directory"):
        store.create_directory("survival")


def test_metadata_path_validates_name(store: ServerStore) -> None:
    with pytest.raises(ValidationError):
        store.path("../escape")


def test_rename_moves_directory(store: ServerStore) -> None:
    server = make_server()
    store.save(server)
    (store.path("survival") / "world").mkdir()

    new_path = store.rename("survival", "creative")

    assert new_path == store.path("creative")
    assert not store.path("survival").exists()
    assert (new_path / "world").is_dir()
    with pytest.raises(ServerError, match="does not exist"):
        store.rename("survival", "other")


def test_rename_rejects_existing_target(store: ServerStore) -> None:
    store.save(make_server("survival"))
    store.save(make_server("creative"))
    with pytest.raises(ServerError, match="already exists"):
        store.rename("survival", "creative")


def test_pid_helpers(store: ServerStore) -> None:
    assert store.read_pid("survival") is None
    store.write_pid("survival", 4242)
    assert store.pid_path("survival").read_text(encoding="utf-8") == "4242\n"
    assert store.read_pid("survival") == 4242
    store.clear_pid("survival")
    assert store.read_pid("survival") is None


def test_is_running_without_pid(store: ServerStore) -> None:
    assert store.is_running("survival") == (False, None)


def test_is_running_rejects_pid_reuse(
    store: ServerStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.write_pid("survival", 4242)

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def is_running(self) -> bool:
            return True

        def status(self) -> str:
            return "running"

        def name(self) -> str:
            return "python.exe"

        def cmdline(self) -> list[str]:
            return ["python.exe", "script.py"]

        def cwd(self) -> str:
            return str(store.root)

    monkeypatch.setattr("slime.store.psutil.Process", FakeProcess)
    assert store.is_running("survival") == (False, 4242)


def test_is_running_accepts_java(
    store: ServerStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.write_pid("survival", 4242)

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def is_running(self) -> bool:
            return True

        def status(self) -> str:
            return "running"

        def name(self) -> str:
            return "java.exe"

        def cmdline(self) -> list[str]:
            return ["java.exe", "-jar", "server.jar"]

        def cwd(self) -> str:
            return str(store.path("survival"))

    monkeypatch.setattr("slime.store.psutil.Process", FakeProcess)
    assert store.is_running("survival") == (True, 4242)


def test_is_running_rejects_foreign_java(
    store: ServerStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.write_pid("survival", 4242)

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def is_running(self) -> bool:
            return True

        def status(self) -> str:
            return "running"

        def name(self) -> str:
            return "java.exe"

        def cmdline(self) -> list[str]:
            return ["java.exe", "-jar", "C:/other-server/server.jar"]

        def cwd(self) -> str:
            return "C:/other-server"

    monkeypatch.setattr("slime.store.psutil.Process", FakeProcess)
    assert store.is_running("survival") == (False, 4242)


def test_utc_now_is_isoformat(store: ServerStore) -> None:
    value = ServerStore.utc_now()
    assert "T" in value
    assert value.endswith("+00:00")


def test_pid_file_name_is_constant() -> None:
    assert PID_FILE == "slime.pid"
    assert METADATA_FILE == "slime.json"
