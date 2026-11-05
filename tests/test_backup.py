"""Tests for compressed server backups."""

from __future__ import annotations

import json
from pathlib import Path

import py7zr
import pytest

from slime.backup import MANIFEST_NAME, BackupManager
from slime.config import Config
from slime.errors import BackupError
from slime.models import Server
from slime.store import ServerStore


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


@pytest.fixture
def manager(tmp_path: Path) -> BackupManager:
    config = Config(tmp_path / "home")
    store = ServerStore(config)
    return BackupManager(config, store)


def prepare_server(manager: BackupManager, server: Server) -> Path:
    manager.store.save(server)
    directory = manager.store.path(server.name)
    (directory / "world" / "region").mkdir(parents=True)
    (directory / "world" / "region" / "r.0.0.mca").write_text(
        "world-data", encoding="utf-8"
    )
    (directory / "world" / "level.dat").write_text("level", encoding="utf-8")
    (directory / "plugins" / "Example").mkdir(parents=True)
    (directory / "plugins" / "Example" / "config.yml").write_text(
        "enabled: true\n", encoding="utf-8"
    )
    (directory / "config").mkdir()
    (directory / "config" / "settings.yml").write_text("x: 1\n", encoding="utf-8")
    (directory / "server.properties").write_text(
        "level-name=world\n", encoding="utf-8"
    )
    (directory / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    (directory / "logs").mkdir()
    (directory / "logs" / "latest.log").write_text("latest\n", encoding="utf-8")
    (directory / "logs" / "2026-01-01-1.log.gz").write_text(
        "archive", encoding="utf-8"
    )
    (directory / "server.jar").write_text("jar", encoding="utf-8")
    return directory


def test_create_writes_archive_sidecar_and_manifest(
    manager: BackupManager,
) -> None:
    server = make_server()
    directory = prepare_server(manager, server)

    info = manager.create(server, note="before upgrade")

    assert info.path.is_file()
    assert info.path.suffix == ".7z"
    assert info.server == server.name
    assert info.project == "paper"
    assert info.minecraft_version == "1.21.4"
    assert info.note == "before upgrade"
    assert info.files == 7
    assert info.size_bytes > 0
    assert info.created_label

    sidecar = info.path.with_suffix(".json")
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["note"] == "before upgrade"
    assert data["files"] == 7

    with py7zr.SevenZipFile(info.path, "r") as archive:
        names = set(archive.getnames())
    assert MANIFEST_NAME in names
    assert "world/region/r.0.0.mca" in names
    assert "plugins/Example/config.yml" in names
    assert "config/settings.yml" in names
    assert "server.properties" in names
    assert "logs/latest.log" in names
    assert "logs/2026-01-01-1.log.gz" not in names
    assert "server.jar" not in names
    assert "slime.json" not in names
    assert (directory / "server.jar").is_file()


def test_create_refuses_a_running_server(
    manager: BackupManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = make_server()
    prepare_server(manager, server)
    monkeypatch.setattr(manager, "is_running", lambda name: True)

    with pytest.raises(BackupError, match="running"):
        manager.create(server)


def test_create_requires_server_content(manager: BackupManager) -> None:
    server = make_server()
    manager.store.save(server)

    with pytest.raises(BackupError, match="Nothing to back up"):
        manager.create(server)


def test_list_resolve_and_delete(manager: BackupManager) -> None:
    server = make_server()
    prepare_server(manager, server)
    first = manager.create(server, note="first")
    second = manager.create(server, note="second")

    backups = manager.list(server.name)
    assert [info.identifier for info in backups] == [
        second.identifier,
        first.identifier,
    ]
    assert manager.list_all() == backups

    assert manager.resolve(server.name, second.identifier) == second
    assert manager.resolve(server.name, f"{second.identifier}.7z") == second

    prefix = second.identifier[: len(second.identifier) - 1]
    assert manager.resolve(server.name, prefix) == second

    manager.delete(server.name, first.identifier)
    assert [info.identifier for info in manager.list(server.name)] == [
        second.identifier
    ]
    assert not first.path.exists()
    assert not first.path.with_suffix(".json").exists()


def test_resolve_reports_missing_and_ambiguous(manager: BackupManager) -> None:
    server = make_server()
    prepare_server(manager, server)
    manager.create(server)
    manager.create(server)

    with pytest.raises(BackupError, match="was not found"):
        manager.resolve(server.name, "does-not-exist")

    with pytest.raises(BackupError, match="ambiguous"):
        manager.resolve(server.name, "20")


def test_restore_replaces_selected_content(manager: BackupManager) -> None:
    server = make_server()
    directory = prepare_server(manager, server)
    info = manager.create(server)

    (directory / "world" / "region" / "r.0.0.mca").write_text(
        "changed", encoding="utf-8"
    )
    (directory / "world" / "region" / "stale.mca").write_text(
        "stale", encoding="utf-8"
    )
    (directory / "plugins" / "Example" / "stale.yml").write_text(
        "stale", encoding="utf-8"
    )
    (directory / "server.properties").write_text(
        "level-name=other\n", encoding="utf-8"
    )
    (directory / "server.jar").write_text("keep-jar", encoding="utf-8")
    (directory / "logs" / "latest.log").write_text("new\n", encoding="utf-8")

    restored = manager.restore(server, info.identifier)

    assert restored == 7
    assert (directory / "world" / "region" / "r.0.0.mca").read_text(
        encoding="utf-8"
    ) == "world-data"
    assert not (directory / "world" / "region" / "stale.mca").exists()
    assert not (directory / "plugins" / "Example" / "stale.yml").exists()
    assert (directory / "plugins" / "Example" / "config.yml").is_file()
    assert (directory / "server.properties").read_text(encoding="utf-8") == (
        "level-name=world\n"
    )
    assert (directory / "logs" / "latest.log").read_text(encoding="utf-8") == (
        "latest\n"
    )
    assert (directory / "logs" / "2026-01-01-1.log.gz").is_file()
    assert (directory / "server.jar").read_text(encoding="utf-8") == "keep-jar"
    assert manager.store.get(server.name) == server


def test_restore_refuses_a_running_server(
    manager: BackupManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = make_server()
    prepare_server(manager, server)
    info = manager.create(server)
    monkeypatch.setattr(manager, "is_running", lambda name: True)

    with pytest.raises(BackupError, match="running"):
        manager.restore(server, info.identifier)


def test_restore_missing_backup(manager: BackupManager) -> None:
    server = make_server()
    prepare_server(manager, server)

    with pytest.raises(BackupError, match="was not found"):
        manager.restore(server, "nope")


@pytest.mark.parametrize(
    "name",
    ["../evil.txt", "/etc/passwd", "C:/Windows/system32", "world/../../evil"],
)
def test_validate_members_rejects_unsafe_paths(name: str) -> None:
    with pytest.raises(BackupError, match="unsafe path"):
        BackupManager._validate_members([name])


def test_validate_members_accepts_normal_paths() -> None:
    BackupManager._validate_members(["world/level.dat", "plugins/x.jar"])


def test_info_helpers(manager: BackupManager) -> None:
    server = make_server()
    prepare_server(manager, server)
    info = manager.create(server, note="note")

    data = info.to_dict()
    assert data["identifier"] == info.identifier
    assert data["size"] == info.size_label
    assert data["server"] == server.name
    assert data["note"] == "note"

    assert manager.list("other") == []


def test_manager_uses_backups_directory(manager: BackupManager) -> None:
    server = make_server()
    assert manager.directory(server.name) == manager.root / server.name
    assert manager.root.name == "backups"
