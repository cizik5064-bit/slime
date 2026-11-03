from __future__ import annotations

from pathlib import Path

import pytest

from slime.config import Config
from slime.errors import ServerError, ValidationError
from slime.models import BuildInfo, DownloadInfo
from slime.provision import CreateRequest, Provisioner
from slime.store import ServerStore


class FakePaperMC:
    def __init__(self) -> None:
        self.build_calls: list[int] = []
        self.latest_calls: list[tuple[str, str]] = []

    def latest_version(self, project: str) -> str:
        return "1.21.4"

    def build(self, project: str, version: str, build: int) -> BuildInfo:
        self.build_calls.append(build)
        return self._build(project, version, build)

    def latest_build(
        self, project: str, version: str, *, channel: str = "STABLE"
    ) -> BuildInfo:
        self.latest_calls.append((version, channel))
        return self._build(project, version, 42)

    @staticmethod
    def _build(project: str, version: str, build: int) -> BuildInfo:
        return BuildInfo(
            project=project,
            version=version,
            build=build,
            channel="STABLE",
            downloads={
                "server:default": DownloadInfo(
                    name=f"{project}-{version}-{build}.jar",
                    url=f"https://example/{project}.jar",
                    sha256="deadbeef",
                    size=4,
                )
            },
        )


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Provisioner, ServerStore, FakePaperMC]:
    config = Config(tmp_path / "home")
    store = ServerStore(config)
    papermc = FakePaperMC()

    def fake_download(url: str, destination: Path, **kwargs: object) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"jar!")
        return destination

    monkeypatch.setattr("slime.provision.download_file", fake_download)
    return Provisioner(config, store, papermc), store, papermc  # type: ignore[arg-type]


def test_create_paper_server(setup: tuple[Provisioner, ServerStore, FakePaperMC]) -> None:
    provisioner, store, _ = setup
    request = CreateRequest(
        name="survival",
        project="paper",
        memory_mb=4096,
        port=25566,
        accept_eula=True,
        motd="Hello",
    )

    server = provisioner.create(request)

    assert server.name == "survival"
    assert server.minecraft_version == "1.21.4"
    assert server.build == 42
    assert server.java_major == 21
    assert server.memory_mb == 4096
    assert server.port == 25566
    assert server.eula_accepted is True
    assert store.get("survival") == server

    directory = store.path("survival")
    assert (directory / "server.jar").read_bytes() == b"jar!"
    assert "server-port=25566" in (directory / "server.properties").read_text(
        encoding="utf-8"
    )
    assert "motd=Hello" in (directory / "server.properties").read_text(
        encoding="utf-8"
    )
    assert "eula=true" in (directory / "eula.txt").read_text(encoding="utf-8")


def test_create_without_eula(setup: tuple[Provisioner, ServerStore, FakePaperMC]) -> None:
    provisioner, store, _ = setup
    server = provisioner.create(CreateRequest(name="survival", project="paper"))
    assert server.eula_accepted is False
    assert "eula=false" in (store.path("survival") / "eula.txt").read_text(
        encoding="utf-8"
    )


def test_create_proxy(setup: tuple[Provisioner, ServerStore, FakePaperMC]) -> None:
    provisioner, store, _ = setup
    server = provisioner.create(CreateRequest(name="proxy", project="velocity"))
    directory = store.path("proxy")
    assert server.java_major == 17
    assert (directory / "server.jar").is_file()
    assert (directory / "SLIME_PROXY.txt").is_file()
    assert not (directory / "server.properties").exists()
    assert not (directory / "eula.txt").exists()


def test_create_purpur_server(
    setup: tuple[Provisioner, ServerStore, FakePaperMC],
) -> None:
    provisioner, store, _ = setup
    server = provisioner.create(
        CreateRequest(name="purpur", project="purpur", accept_eula=True)
    )
    directory = store.path("purpur")
    assert server.project == "purpur"
    assert server.java_major == 21
    assert (directory / "server.jar").is_file()
    assert (directory / "server.properties").is_file()
    assert "eula=true" in (directory / "eula.txt").read_text(encoding="utf-8")


def test_explicit_build_and_version(
    setup: tuple[Provisioner, ServerStore, FakePaperMC],
) -> None:
    provisioner, _, papermc = setup
    server = provisioner.create(
        CreateRequest(name="survival", project="paper", version="1.20.4", build=7)
    )
    assert server.build == 7
    assert papermc.build_calls == [7]
    assert papermc.latest_calls == []


def test_channel_is_forwarded(setup: tuple[Provisioner, ServerStore, FakePaperMC]) -> None:
    provisioner, _, papermc = setup
    provisioner.create(
        CreateRequest(name="survival", project="paper", version="1.21.4", channel="beta")
    )
    assert papermc.latest_calls == [("1.21.4", "beta")]


def test_existing_server_rejected(
    setup: tuple[Provisioner, ServerStore, FakePaperMC],
) -> None:
    provisioner, store, _ = setup
    store.save(provisioner.create(CreateRequest(name="survival", project="paper")))
    with pytest.raises(ServerError, match="already exists"):
        provisioner.create(CreateRequest(name="survival", project="paper"))


def test_invalid_memory_and_port(
    setup: tuple[Provisioner, ServerStore, FakePaperMC],
) -> None:
    provisioner, _, _ = setup
    with pytest.raises(ValidationError):
        provisioner.create(
            CreateRequest(name="bad-memory", project="paper", memory_mb=1)
        )
    with pytest.raises(ValidationError):
        provisioner.create(CreateRequest(name="bad-port", project="paper", port=0))


def test_failed_download_cleans_directory(
    setup: tuple[Provisioner, ServerStore, FakePaperMC],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioner, store, _ = setup

    def broken_download(*_: object, **__: object) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr("slime.provision.download_file", broken_download)
    with pytest.raises(OSError):
        provisioner.create(CreateRequest(name="survival", project="paper"))
    assert not store.path("survival").exists()


def test_failed_download_keeps_preexisting_empty_directory(
    setup: tuple[Provisioner, ServerStore, FakePaperMC],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioner, store, _ = setup
    directory = store.path("survival")
    directory.mkdir(parents=True)

    def broken_download(*_: object, **__: object) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr("slime.provision.download_file", broken_download)
    with pytest.raises(OSError):
        provisioner.create(CreateRequest(name="survival", project="paper"))
    assert directory.is_dir()


def test_progress_reports_stages(
    setup: tuple[Provisioner, ServerStore, FakePaperMC],
) -> None:
    provisioner, _, _ = setup
    events: list[tuple[str, int, int | None]] = []
    provisioner.create(
        CreateRequest(name="survival", project="paper"),
        progress=lambda stage, done, total: events.append((stage, done, total)),
    )
    assert events[0][0] == "Downloading server jar"
    assert events[-1] == ("Server created", 1, 1)
