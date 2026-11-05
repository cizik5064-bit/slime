from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slime import __version__
from slime.cli import app
from slime.models import BuildInfo, DownloadInfo, Server


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home"
    monkeypatch.setenv("SLIME_HOME", str(path))
    return path


class FakePaperMC:
    def latest_version(self, project: str) -> str:
        return "1.21.4"

    def build(self, project: str, version: str, build: int) -> BuildInfo:
        return self._build(project, version, build)

    def latest_build(
        self, project: str, version: str, *, channel: str = "STABLE"
    ) -> BuildInfo:
        return self._build(project, version, 42)

    def versions(self, project: str) -> list[str]:
        return ["1.21.4", "1.20.6"]

    def builds(self, project: str, version: str) -> list[BuildInfo]:
        return [self._build(project, version, 1), self._build(project, version, 2)]

    @staticmethod
    def _build(project: str, version: str, build: int) -> BuildInfo:
        return BuildInfo(
            project=project,
            version=version,
            build=build,
            channel="STABLE",
            time="2026-01-01T00:00:00Z",
            downloads={
                "server:default": DownloadInfo(
                    name=f"{project}-{version}-{build}.jar",
                    url=f"https://example/{project}.jar",
                    sha256="deadbeef",
                    size=4,
                )
            },
        )


def test_version(runner: CliRunner, home: Path) -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"Slime {__version__}" in result.output


def test_config_show_json(runner: CliRunner, home: Path) -> None:
    result = runner.invoke(app, ["config", "show", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["settings"]["default_memory_mb"] == 2048
    assert Path(payload["paths"]["home"]) == home


def test_config_set_and_show(runner: CliRunner, home: Path) -> None:
    result = runner.invoke(app, ["config", "set", "default_memory_mb", "4096"])
    assert result.exit_code == 0
    assert "4096" in result.output

    result = runner.invoke(app, ["config", "show", "--json"])
    payload = json.loads(result.output)
    assert payload["settings"]["default_memory_mb"] == 4096


def test_config_set_invalid(runner: CliRunner, home: Path) -> None:
    result = runner.invoke(app, ["config", "set", "unknown", "1"])
    assert result.exit_code == 1
    assert "Unknown setting" in result.output


def test_config_path(runner: CliRunner, home: Path) -> None:
    result = runner.invoke(app, ["config", "path"])
    assert result.exit_code == 0
    assert str(home) in result.output.replace("\n", "")


def test_server_list_empty_json(runner: CliRunner, home: Path) -> None:
    result = runner.invoke(app, ["server", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_server_list_empty_text(runner: CliRunner, home: Path) -> None:
    result = runner.invoke(app, ["server", "list"])
    assert result.exit_code == 0
    assert "No servers yet" in result.output


def test_server_path_missing(runner: CliRunner, home: Path) -> None:
    result = runner.invoke(app, ["server", "path", "missing"])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_server_eula_and_info(
    runner: CliRunner, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slime.config import Config
    from slime.store import ServerStore

    config = Config(home)
    store = ServerStore(config)
    server = Server(
        name="survival",
        project="paper",
        minecraft_version="1.21.4",
        build=42,
        java_major=21,
    )
    store.save(server)

    result = runner.invoke(app, ["server", "eula", "survival", "--accept"])
    assert result.exit_code == 0
    assert "EULA accepted" in result.output
    assert store.get("survival").eula_accepted is True

    result = runner.invoke(app, ["server", "info", "survival", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["name"] == "survival"
    assert payload["path"] == str(store.path("survival"))


def test_server_eula_requires_explicit_flag_non_interactive(
    runner: CliRunner, home: Path
) -> None:
    from slime.config import Config
    from slime.store import ServerStore

    store = ServerStore(Config(home))
    store.save(
        Server(
            name="survival",
            project="paper",
            minecraft_version="1.21.4",
            build=42,
            java_major=21,
        )
    )

    result = runner.invoke(app, ["server", "eula", "survival"])
    assert result.exit_code == 1
    assert "--accept or --revoke" in result.output
    assert store.get("survival").eula_accepted is False
    assert not (store.path("survival") / "eula.txt").exists()


def test_doctor_json(runner: CliRunner, home: Path) -> None:
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert {item["id"] for item in payload} >= {"python", "os", "home", "disk"}


def test_server_create_with_fake_api(
    runner: CliRunner, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("slime.cli.ProjectCatalog", lambda *a, **k: FakePaperMC())

    def fake_download(url: str, destination: Path, **kwargs: object) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"jar!")
        return destination

    monkeypatch.setattr("slime.provision.download_file", fake_download)

    result = runner.invoke(
        app,
        [
            "server",
            "create",
            "survival",
            "--project",
            "paper",
            "--memory",
            "2048",
            "--accept-eula",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Server created" in result.output
    assert (home / "servers" / "survival" / "server.jar").is_file()


def test_server_create_requires_project_non_interactive(
    runner: CliRunner, home: Path
) -> None:
    result = runner.invoke(app, ["server", "create", "survival"])
    assert result.exit_code == 1
    assert "Missing --project" in result.output

def _prepare_backup_server(home: Path) -> tuple[Path, str]:
    from slime.config import Config
    from slime.store import ServerStore

    store = ServerStore(Config(home))
    store.save(
        Server(
            name="survival",
            project="paper",
            minecraft_version="1.21.4",
            build=42,
            java_major=21,
        )
    )
    directory = store.path("survival")
    (directory / "world" / "region").mkdir(parents=True)
    (directory / "world" / "region" / "r.0.0.mca").write_text(
        "world", encoding="utf-8"
    )
    (directory / "server.properties").write_text(
        "level-name=world\n", encoding="utf-8"
    )
    return directory, "survival"


def test_backup_create_list_path_and_delete(runner: CliRunner, home: Path) -> None:
    directory, name = _prepare_backup_server(home)

    result = runner.invoke(app, ["backup", "create", name, "--note", "before"])
    assert result.exit_code == 0, result.output
    assert "Backup created" in result.output
    assert "before" in result.output

    result = runner.invoke(app, ["backup", "list", name, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload) == 1
    info = payload[0]
    assert info["server"] == name
    assert info["note"] == "before"
    assert info["files"] == 2
    assert Path(info["path"]).is_file()

    result = runner.invoke(app, ["backup", "path", name])
    assert result.exit_code == 0
    assert str(home / "backups" / name) in result.output.replace("\n", "")

    result = runner.invoke(app, ["backup", "path"])
    assert result.exit_code == 0
    assert str(home / "backups") in result.output.replace("\n", "")

    result = runner.invoke(app, ["backup", "list", name])
    assert result.exit_code == 0
    assert info["identifier"] in result.output

    result = runner.invoke(
        app, ["backup", "delete", name, info["identifier"], "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert "Deleted" in result.output
    assert not Path(info["path"]).exists()
    assert (directory / "world" / "region" / "r.0.0.mca").is_file()


def test_backup_list_empty_and_unknown_server(
    runner: CliRunner, home: Path
) -> None:
    result = runner.invoke(app, ["backup", "list"])
    assert result.exit_code == 0
    assert "No backups yet" in result.output

    result = runner.invoke(app, ["backup", "list", "missing"])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_backup_restore_round_trip(runner: CliRunner, home: Path) -> None:
    directory, name = _prepare_backup_server(home)
    world_file = directory / "world" / "region" / "r.0.0.mca"

    result = runner.invoke(app, ["backup", "create", name])
    assert result.exit_code == 0, result.output
    payload = json.loads(
        runner.invoke(app, ["backup", "list", name, "--json"]).output
    )
    identifier = payload[0]["identifier"]

    world_file.write_text("broken", encoding="utf-8")
    (directory / "world" / "region" / "stale.mca").write_text(
        "stale", encoding="utf-8"
    )

    result = runner.invoke(
        app, ["backup", "restore", name, identifier, "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert "Restored" in result.output
    assert world_file.read_text(encoding="utf-8") == "world"
    assert not (directory / "world" / "region" / "stale.mca").exists()


def test_backup_delete_requires_confirmation_non_interactive(
    runner: CliRunner, home: Path
) -> None:
    _, name = _prepare_backup_server(home)
    assert runner.invoke(app, ["backup", "create", name]).exit_code == 0
    payload = json.loads(
        runner.invoke(app, ["backup", "list", name, "--json"]).output
    )

    result = runner.invoke(
        app, ["backup", "delete", name, payload[0]["identifier"]]
    )
    assert result.exit_code == 1
    assert "--yes" in result.output
    assert Path(payload[0]["path"]).is_file()


def test_config_show_includes_backups_path(runner: CliRunner, home: Path) -> None:
    result = runner.invoke(app, ["config", "show", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert Path(payload["paths"]["backups"]) == home / "backups"
