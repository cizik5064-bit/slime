from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

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

# ---------------------------------------------------------------------------
# RCON commands
# ---------------------------------------------------------------------------


class FakeRconClient:
    instances: ClassVar[list[FakeRconClient]] = []

    def __init__(self, config, *, timeout: float = 5.0) -> None:
        self.config = config
        self.timeout = timeout
        self.commands: list[str] = []
        FakeRconClient.instances.append(self)

    def __enter__(self) -> FakeRconClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def command(self, command: str) -> str:
        self.commands.append(command)
        return f"response to {command}"


def _prepare_rcon_server(home: Path) -> Server:
    from slime.config import Config
    from slime.store import ServerStore

    store = ServerStore(Config(home))
    server = Server(
        name="survival",
        project="paper",
        minecraft_version="1.21.4",
        build=42,
        java_major=21,
        port=25565,
    )
    store.save(server)
    (store.path("survival") / "server.properties").write_text(
        "enable-rcon=true\nrcon.port=25575\nrcon.password=secret\n",
        encoding="utf-8",
    )
    return server


def test_server_cmd_sends_a_command(
    runner: CliRunner, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prepare_rcon_server(home)
    FakeRconClient.instances = []
    monkeypatch.setattr("slime.cli.RconClient", FakeRconClient)

    result = runner.invoke(app, ["server", "cmd", "survival", "say", "hello"])

    assert result.exit_code == 0, result.output
    assert "response to say hello" in result.output
    assert FakeRconClient.instances[0].commands == ["say hello"]


def test_server_console_reads_commands_until_exit(
    runner: CliRunner, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prepare_rcon_server(home)
    FakeRconClient.instances = []
    monkeypatch.setattr("slime.cli.RconClient", FakeRconClient)

    result = runner.invoke(
        app, ["server", "console", "survival"], input="list\nexit\n"
    )

    assert result.exit_code == 0, result.output
    assert "response to list" in result.output
    assert FakeRconClient.instances[0].commands == ["list"]


def test_server_stop_uses_rcon_and_waits_for_exit(
    runner: CliRunner, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slime.store import ServerStore

    _prepare_rcon_server(home)
    FakeRconClient.instances = []
    monkeypatch.setattr("slime.cli.RconClient", FakeRconClient)
    calls = {"count": 0}

    def fake_is_running(self: ServerStore, name: str) -> tuple[bool, int | None]:
        calls["count"] += 1
        return calls["count"] == 1, 4321

    monkeypatch.setattr(ServerStore, "is_running", fake_is_running)

    result = runner.invoke(app, ["server", "stop", "survival"])

    assert result.exit_code == 0, result.output
    assert "stop" in FakeRconClient.instances[0].commands
    assert "stopped" in result.output.lower()


def test_server_cmd_requires_rcon_to_be_enabled(
    runner: CliRunner, home: Path, monkeypatch: pytest.MonkeyPatch
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
    FakeRconClient.instances = []
    monkeypatch.setattr("slime.cli.RconClient", FakeRconClient)

    result = runner.invoke(app, ["server", "cmd", "survival", "list"])

    assert result.exit_code == 1
    assert "RCON is not enabled" in result.output

# ---------------------------------------------------------------------------
# Additional command coverage
# ---------------------------------------------------------------------------


def _prepare_server(home: Path, name: str = "survival", **overrides: object) -> Server:
    from slime.config import Config
    from slime.store import ServerStore

    values: dict[str, object] = {
        "name": name,
        "project": "paper",
        "minecraft_version": "1.21.4",
        "build": 42,
        "java_major": 21,
        "eula_accepted": True,
    }
    values.update(overrides)
    server = Server(**values)  # type: ignore[arg-type]
    ServerStore(Config(home)).save(server)
    return server


def test_server_list_text_and_server_path(runner: CliRunner, home: Path) -> None:
    _prepare_server(home)
    result = runner.invoke(app, ["server", "list"])
    assert result.exit_code == 0, result.output
    assert "survival" in result.output

    result = runner.invoke(app, ["server", "path", "survival"])
    assert result.exit_code == 0, result.output
    # Rich may wrap long temporary paths; compare without whitespace.
    assert "".join(result.output.split()).endswith("survival")


def test_config_show_text(runner: CliRunner, home: Path) -> None:
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert "default_memory_mb" in result.output


def test_server_versions_text_and_json(
    runner: CliRunner, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("slime.cli.ProjectCatalog", lambda *a, **k: FakePaperMC())

    result = runner.invoke(app, ["server", "versions", "--limit", "1"])
    assert result.exit_code == 0, result.output
    assert "1.21.4" in result.output
    assert "more; use --limit" in result.output

    result = runner.invoke(app, ["server", "versions", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == ["1.21.4", "1.20.6"]


def test_server_builds_text_and_json(
    runner: CliRunner, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("slime.cli.ProjectCatalog", lambda *a, **k: FakePaperMC())

    result = runner.invoke(app, ["server", "builds", "1.21.4"])
    assert result.exit_code == 0, result.output
    assert "paper-1.21.4-1.jar" in result.output
    assert "0.0 MiB" in result.output

    result = runner.invoke(
        app, ["server", "builds", "1.21.4", "--channel", "STABLE", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [item["build"] for item in payload] == [2, 1]


def test_server_info_json_includes_checks(
    runner: CliRunner, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slime.checks import CheckResult, CheckStatus

    _prepare_server(home)

    def fake_checks(*args: object, **kwargs: object) -> list[CheckResult]:
        return [CheckResult("files", "Files", CheckStatus.OK, "present")]

    monkeypatch.setattr("slime.cli.run_checks", fake_checks)

    result = runner.invoke(app, ["server", "info", "survival", "--checks", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["name"] == "survival"
    assert payload["checks"][0]["id"] == "files"


def test_server_info_text_reports_missing_java(
    runner: CliRunner, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prepare_server(home)
    # CI images may ship a system Java, so force the "not installed" branch.
    monkeypatch.setattr("slime.cli.JavaManager.find_for", lambda self, server: None)
    result = runner.invoke(app, ["server", "info", "survival"])
    assert result.exit_code == 0, result.output
    assert "not installed" in result.output
    assert "EULA" in result.output


def test_doctor_text_output(runner: CliRunner, home: Path) -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code in {0, 2}, result.output
    assert "Environment check" in result.output
    assert "error(s)" in result.output


def test_server_delete_requires_confirmation_non_interactive(
    runner: CliRunner, home: Path
) -> None:
    _prepare_server(home)
    result = runner.invoke(app, ["server", "delete", "survival"])
    assert result.exit_code == 1
    assert "Refusing to delete" in result.output


def test_server_delete_with_yes_removes_the_directory(
    runner: CliRunner, home: Path
) -> None:
    _prepare_server(home)
    result = runner.invoke(app, ["server", "delete", "survival", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Deleted" in result.output
    assert not (home / "servers" / "survival").exists()


def test_server_delete_keep_files_unregisters(
    runner: CliRunner, home: Path
) -> None:
    _prepare_server(home)
    result = runner.invoke(
        app, ["server", "delete", "survival", "--yes", "--keep-files"]
    )
    assert result.exit_code == 0, result.output
    assert "Unregistered" in result.output
    assert (home / "servers" / "survival").is_dir()


def test_server_delete_refuses_a_running_server(
    runner: CliRunner, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slime.store import ServerStore

    _prepare_server(home)
    monkeypatch.setattr(ServerStore, "is_running", lambda self, name: (True, 42))
    result = runner.invoke(app, ["server", "delete", "survival", "--yes"])
    assert result.exit_code == 1
    assert "is running" in result.output


def test_server_run_refuses_a_running_server(
    runner: CliRunner, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slime.store import ServerStore

    _prepare_server(home)
    monkeypatch.setattr(ServerStore, "is_running", lambda self, name: (True, 42))
    result = runner.invoke(app, ["server", "run", "survival"])
    assert result.exit_code == 1
    assert "already running" in result.output
    assert "server stop survival" in result.output


def test_server_run_reports_a_missing_jar(
    runner: CliRunner, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slime.models import JavaInstall

    _prepare_server(home)
    monkeypatch.setattr(
        "slime.cli.JavaManager.require_for",
        lambda self, server: JavaInstall(
            major=21,
            version="21",
            path="java",
            home="home",
        ),
    )
    result = runner.invoke(app, ["server", "run", "survival"])
    assert result.exit_code == 1
    assert "jar is missing" in result.output


def test_server_run_requires_eula(
    runner: CliRunner, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slime.models import JavaInstall

    _prepare_server(home, eula_accepted=False)
    monkeypatch.setattr(
        "slime.cli.JavaManager.require_for",
        lambda self, server: JavaInstall(
            major=21,
            version="21",
            path="java",
            home="home",
        ),
    )
    result = runner.invoke(app, ["server", "run", "survival"])
    assert result.exit_code == 1
    assert "EULA has not been accepted" in result.output


def test_no_subcommand_without_a_tty_prints_help(
    runner: CliRunner, home: Path
) -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0, result.output
    assert "Usage" in result.output
