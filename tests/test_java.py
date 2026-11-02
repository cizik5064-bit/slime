from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from slime.api.adoptium import JavaPackage
from slime.config import Config
from slime.errors import JavaError
from slime.java import METADATA_FILE, JavaManager, _java_major
from slime.models import JavaInstall, Server


def make_server(**overrides: object) -> Server:
    values: dict[str, object] = {
        "name": "survival",
        "project": "paper",
        "minecraft_version": "1.21.4",
        "build": 232,
        "java_major": 21,
    }
    values.update(overrides)
    return Server(**values)  # type: ignore[arg-type]


def executable_name() -> str:
    return "java.exe" if os.name == "nt" else "java"


def create_install(root: Path, major: int = 21) -> JavaInstall:
    home = root / f"temurin-{major}-windows-x64"
    path = home / "bin" / executable_name()
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")
    install = JavaInstall(
        major=major,
        version=f"{major}.0.1",
        path=str(path),
        home=str(home),
        os="windows",
        arch="x64",
    )
    (home / METADATA_FILE).write_text(
        json.dumps(install.to_dict()), encoding="utf-8"
    )
    return install


class FakeAdoptium:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, str]] = []

    def latest_package(
        self, major: int, *, os_name: str | None = None, arch: str | None = None
    ) -> JavaPackage:
        self.calls.append((major, str(os_name), str(arch)))
        return JavaPackage(
            major=major,
            version=f"{major}.0.4+7",
            os=str(os_name),
            arch=str(arch),
            name=f"temurin-{major}.zip",
            url="https://example/temurin.zip",
            sha256="deadbeef",
            size=4,
        )


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("21.0.4", 21),
        ("1.8.0_402", 8),
        ("17", 17),
        ("", None),
        ("not-a-version", None),
    ],
)
def test_java_major(version: str, expected: int | None) -> None:
    assert _java_major(version) == expected


def test_inspect_parses_java_properties(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / executable_name()
    executable.write_text("", encoding="utf-8")
    output = (
        "    java.version = 21.0.4\n"
        "    java.home = C:\\Java\\jdk-21\n"
    )
    completed = subprocess.CompletedProcess([], 0, stdout=output, stderr="")
    monkeypatch.setattr("slime.java.subprocess.run", lambda *a, **k: completed)

    manager = JavaManager(Config(tmp_path / "home"), FakeAdoptium())  # type: ignore[arg-type]
    install = manager.inspect(executable)
    assert install is not None
    assert install.major == 21
    assert install.version == "21.0.4"
    assert install.home == "C:\\Java\\jdk-21"
    assert install.source == "system"


def test_inspect_returns_none_for_bad_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / executable_name()
    executable.write_text("", encoding="utf-8")
    completed = subprocess.CompletedProcess([], 0, stdout="nonsense", stderr="")
    monkeypatch.setattr("slime.java.subprocess.run", lambda *a, **k: completed)
    manager = JavaManager(Config(tmp_path / "home"), FakeAdoptium())  # type: ignore[arg-type]
    assert manager.inspect(executable) is None


def test_inspect_missing_or_broken(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JavaManager(Config(tmp_path / "home"), FakeAdoptium())  # type: ignore[arg-type]
    assert manager.inspect(tmp_path / "missing") is None

    executable = tmp_path / executable_name()
    executable.write_text("", encoding="utf-8")

    def fail(*_: object, **__: object) -> None:
        raise OSError("cannot run")

    monkeypatch.setattr("slime.java.subprocess.run", fail)
    assert manager.inspect(executable) is None


def test_installed_reads_metadata(tmp_path: Path) -> None:
    config = Config(tmp_path / "home")
    install = create_install(config.paths.java)
    manager = JavaManager(config, FakeAdoptium())  # type: ignore[arg-type]
    assert manager.installed() == [install]
    assert manager.get(21) == install
    assert manager.get(17) is None


def test_installed_falls_back_to_bin_java(tmp_path: Path) -> None:
    config = Config(tmp_path / "home")
    home = config.paths.java / "temurin-17-linux-x64"
    path = home / "bin" / executable_name()
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")

    manager = JavaManager(config, FakeAdoptium())  # type: ignore[arg-type]
    installed = manager.installed()
    assert len(installed) == 1
    assert installed[0].major == 17
    assert installed[0].home == str(home)


def test_install_downloads_extracts_and_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config(tmp_path / "home")
    client = FakeAdoptium()
    manager = JavaManager(config, client)  # type: ignore[arg-type]

    def fake_download(url: str, archive: Path, **kwargs: object) -> Path:
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(b"zip!")
        return archive

    def fake_extract(archive: Path, staging: Path) -> None:
        (staging / "jdk-21" / "bin").mkdir(parents=True)

    def fake_find(staging: Path, **kwargs: object) -> Path:
        executable = staging / "jdk-21" / "bin" / executable_name()
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("", encoding="utf-8")
        return executable

    monkeypatch.setattr("slime.java.download_file", fake_download)
    monkeypatch.setattr("slime.java.extract_archive", fake_extract)
    monkeypatch.setattr("slime.java.find_java_executable", fake_find)
    monkeypatch.setattr(
        JavaManager,
        "inspect",
        lambda self, path: JavaInstall(
            major=21,
            version="21.0.4",
            path=str(path),
            home=str(Path(path).parent.parent),
            source="system",
        ),
    )

    install = manager.install(21, os_name="windows", arch="x64")
    assert install.major == 21
    assert install.version == "21.0.4"
    assert Path(install.home) == config.paths.java / "temurin-21-windows-x64"
    assert Path(install.path).is_file()
    assert (Path(install.home) / METADATA_FILE).is_file()
    assert client.calls == [(21, "windows", "x64")]


def test_install_returns_existing_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config(tmp_path / "home")
    install = create_install(config.paths.java)
    manager = JavaManager(config, FakeAdoptium())  # type: ignore[arg-type]
    assert manager.install(21) == install


def test_remove_managed_runtime(tmp_path: Path) -> None:
    config = Config(tmp_path / "home")
    install = create_install(config.paths.java)
    manager = JavaManager(config, FakeAdoptium())  # type: ignore[arg-type]
    assert manager.remove(21) is True
    assert not Path(install.home).exists()
    assert manager.remove(21) is False


def test_remove_refuses_outside_java_root(tmp_path: Path) -> None:
    config = Config(tmp_path / "home")
    outside = tmp_path / "outside"
    path = outside / "bin" / executable_name()
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")
    install = JavaInstall(
        major=21, version="21", path=str(path), home=str(outside)
    )
    managed_dir = config.paths.java / "temurin-21-windows-x64"
    managed_dir.mkdir(parents=True)
    (managed_dir / METADATA_FILE).write_text(
        json.dumps(install.to_dict()), encoding="utf-8"
    )

    manager = JavaManager(config, FakeAdoptium())  # type: ignore[arg-type]
    with pytest.raises(JavaError, match="outside Slime"):
        manager.remove(21)
    assert outside.is_dir()


def test_remove_refuses_java_root(tmp_path: Path) -> None:
    config = Config(tmp_path / "home")
    executable = config.paths.java / "bin" / executable_name()
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    install = JavaInstall(
        major=21, version="21", path=str(executable), home=str(config.paths.java)
    )
    managed_dir = config.paths.java / "temurin-21-windows-x64"
    managed_dir.mkdir()
    (managed_dir / METADATA_FILE).write_text(
        json.dumps(install.to_dict()), encoding="utf-8"
    )

    manager = JavaManager(config, FakeAdoptium())  # type: ignore[arg-type]
    with pytest.raises(JavaError, match="not a managed Java runtime"):
        manager.remove(21)
    assert config.paths.java.is_dir()


def test_system_java_and_find_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config(tmp_path / "home")
    manager = JavaManager(config, FakeAdoptium())  # type: ignore[arg-type]
    install = JavaInstall(
        major=21, version="21.0.1", path=str(tmp_path / "java"), home=str(tmp_path)
    )
    monkeypatch.setattr(manager, "system_java", lambda: install)

    assert manager.find_for(make_server()) == install
    assert manager.find_for(make_server(java_major=17)) is None
    assert manager.require_for(make_server()) == install

    with pytest.raises(JavaError, match="Java 17 is required"):
        manager.require_for(make_server(java_major=17))


def test_find_for_explicit_java_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config(tmp_path / "home")
    manager = JavaManager(config, FakeAdoptium())  # type: ignore[arg-type]
    install = JavaInstall(
        major=21, version="21.0.1", path=str(tmp_path / "java"), home=str(tmp_path)
    )
    monkeypatch.setattr(manager, "inspect", lambda path: install)

    server = make_server(java_path=str(tmp_path / "java"))
    assert manager.find_for(server) == install
    assert manager.find_for(make_server(java_path="missing", java_major=17)) is None


def test_require_for_bad_explicit_path(tmp_path: Path) -> None:
    config = Config(tmp_path / "home")
    manager = JavaManager(config, FakeAdoptium())  # type: ignore[arg-type]
    server = make_server(java_path="/missing/java")
    with pytest.raises(JavaError, match="configured Java path"):
        manager.require_for(server)
