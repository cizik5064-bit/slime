from __future__ import annotations

import pytest

from slime.errors import ValidationError
from slime.models import (
    BuildInfo,
    DownloadInfo,
    JavaInstall,
    Project,
    Server,
    required_java_major,
    sort_versions,
    validate_java_major,
    validate_memory,
    validate_port,
    validate_server_name,
    version_key,
)


class TestProject:
    def test_parse_accepts_strings_and_enum(self) -> None:
        assert Project.parse("paper") is Project.PAPER
        assert Project.parse(" PAPER ") is Project.PAPER
        assert Project.parse(Project.VELOCITY) is Project.VELOCITY
        assert Project.parse("purpur") is Project.PURPUR

    def test_parse_rejects_unknown(self) -> None:
        with pytest.raises(ValidationError, match="Unknown project"):
            Project.parse("fabric")

    def test_properties(self) -> None:
        assert Project.PAPER.display_name == "Paper"
        assert Project.VELOCITY.is_proxy is True
        assert Project.PAPER.is_proxy is False
        assert Project.PURPUR.display_name == "Purpur"
        assert Project.PURPUR.kind == "server"
        assert Project.WATERFALL.kind == "proxy"
        assert Project.FOLIA.kind == "server"


class TestValidation:
    @pytest.mark.parametrize("name", ["survival", "my-server", "a", "A_1", "x" * 32])
    def test_valid_server_names(self, name: str) -> None:
        assert validate_server_name(name) == name

    @pytest.mark.parametrize(
        "name",
        ["", " ", "-bad", "_bad", "bad name", "bad/name", "x" * 33, "café"],
    )
    def test_invalid_server_names(self, name: str) -> None:
        with pytest.raises(ValidationError):
            validate_server_name(name)

    @pytest.mark.parametrize("name", ["CON", "con", "PRN", "COM1", "LPT9", "NUL"])
    def test_reserved_windows_names(self, name: str) -> None:
        with pytest.raises(ValidationError, match="reserved"):
            validate_server_name(name)

    @pytest.mark.parametrize("port", [1, 25565, 65535])
    def test_valid_ports(self, port: int) -> None:
        assert validate_port(port) == port

    @pytest.mark.parametrize("port", [0, -1, 65536, True, "25565"])
    def test_invalid_ports(self, port: object) -> None:
        with pytest.raises(ValidationError):
            validate_port(port)  # type: ignore[arg-type]

    @pytest.mark.parametrize("memory", [512, 2048, 65536])
    def test_valid_memory(self, memory: int) -> None:
        assert validate_memory(memory) == memory

    @pytest.mark.parametrize("memory", [511, 0, 65537, True])
    def test_invalid_memory(self, memory: object) -> None:
        with pytest.raises(ValidationError):
            validate_memory(memory)  # type: ignore[arg-type]

    @pytest.mark.parametrize("major", [8, 11, 16, 17, 21, 25])
    def test_valid_java(self, major: int) -> None:
        assert validate_java_major(major) == major

    @pytest.mark.parametrize("major", [7, 9, 19, 26, "21"])
    def test_invalid_java(self, major: object) -> None:
        with pytest.raises(ValidationError):
            validate_java_major(major)  # type: ignore[arg-type]


class TestVersions:
    def test_version_key_orders_releases_above_prereleases(self) -> None:
        assert version_key("1.21.4") > version_key("1.21.4-rc1")
        assert version_key("1.21.10") > version_key("1.21.9")
        assert version_key("26.3") > version_key("1.21.11")

    def test_snapshots_sort_below_releases(self) -> None:
        assert version_key("24w14a") < version_key("1.20.5")

    def test_sort_versions_newest_first(self) -> None:
        versions = ["1.20.4", "1.21.4", "1.19.4", "1.21.10"]
        assert sort_versions(versions) == ["1.21.10", "1.21.4", "1.20.4", "1.19.4"]

    def test_unknown_versions_are_deterministic(self) -> None:
        assert sort_versions(["weird", "weird"]) == ["weird", "weird"]

    @pytest.mark.parametrize(
        ("project", "version", "expected"),
        [
            ("paper", "1.16.5", 8),
            ("paper", "1.16.6", 8),
            ("paper", "1.17", 17),
            ("paper", "1.20.4", 17),
            ("paper", "1.20.5", 21),
            ("paper", "1.21.11", 21),
            ("folia", "1.21.4", 21),
            ("purpur", "1.21.8", 21),
            ("purpur", "26.3", 25),
            ("paper", "26.1", 25),
            ("paper", "26.3", 25),
            ("paper", "24w14a", 21),
            ("velocity", "1.21.4", 17),
            ("waterfall", "1.21.4", 11),
        ],
    )
    def test_required_java_major(self, project: str, version: str, expected: int) -> None:
        assert required_java_major(project, version) == expected


class TestServer:
    def make(self, **overrides: object) -> Server:
        values: dict[str, object] = {
            "name": "survival",
            "project": "paper",
            "minecraft_version": "1.21.4",
            "build": 232,
            "java_major": 21,
        }
        values.update(overrides)
        return Server(**values)  # type: ignore[arg-type]

    def test_defaults_and_properties(self) -> None:
        server = self.make()
        assert server.memory_mb == 2048
        assert server.min_memory_mb is None
        assert server.cpu_cores is None
        assert server.port == 25565
        assert server.jar_file == "server.jar"
        assert server.is_proxy is False
        assert server.kind == "server"
        assert server.created_at
        assert server.extra_args

    def test_round_trip(self) -> None:
        server = self.make(
            memory_mb=4096,
            min_memory_mb=1024,
            cpu_cores=2,
            port=25566,
            java_path=r"C:\Java\bin\java.exe",
            eula_accepted=True,
            extra_args=["-Dfoo=bar"],
            recovery_args=["--safeMode"],
        )
        restored = Server.from_dict(server.to_dict())
        assert restored == server

    def test_minimum_memory_cannot_exceed_maximum(self) -> None:
        with pytest.raises(ValidationError, match="Minimum memory"):
            self.make(memory_mb=2048, min_memory_mb=4096)

    def test_invalid_cpu_cores_rejected(self) -> None:
        with pytest.raises(ValidationError, match="CPU cores"):
            self.make(cpu_cores=0)

    def test_from_dict_requires_name(self) -> None:
        with pytest.raises(ValidationError, match="name"):
            Server.from_dict({"minecraft_version": "1.21.4"})

    def test_from_dict_requires_version(self) -> None:
        with pytest.raises(ValidationError, match="minecraft_version"):
            Server.from_dict({"name": "survival"})

    def test_jar_file_must_be_plain(self) -> None:
        with pytest.raises(ValidationError):
            self.make(jar_file="../server.jar")

    def test_from_dict_wraps_invalid_integer(self) -> None:
        with pytest.raises(ValidationError, match="build"):
            Server.from_dict(
                {
                    "name": "survival",
                    "minecraft_version": "1.21.4",
                    "build": "abc",
                }
            )

    def test_from_dict_rejects_extra_args_string(self) -> None:
        with pytest.raises(ValidationError, match="extra_args"):
            Server.from_dict(
                {
                    "name": "survival",
                    "minecraft_version": "1.21.4",
                    "extra_args": "--foo",
                }
            )

    def test_from_dict_rejects_recovery_args_string(self) -> None:
        with pytest.raises(ValidationError, match="recovery_args"):
            Server.from_dict(
                {
                    "name": "survival",
                    "minecraft_version": "1.21.4",
                    "recovery_args": "--safeMode",
                }
            )

    def test_from_dict_normalizes_optional_fields(self) -> None:
        server = Server.from_dict(
            {
                "name": "survival",
                "minecraft_version": "1.21.4",
                "extra_args": ["-Dfoo=bar"],
                "java_path": "",
            }
        )
        assert server.extra_args == ["-Dfoo=bar"]
        assert server.java_path is None
        assert server.created_at

    def test_empty_version_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self.make(minecraft_version="  ")


class TestBuildInfo:
    def test_prefers_server_default(self) -> None:
        build = BuildInfo(
            project="paper",
            version="1.21.4",
            build=1,
            downloads={
                "server": DownloadInfo("a.jar", "https://a"),
                "server:default": DownloadInfo("b.jar", "https://b"),
            },
        )
        assert build.server_download.name == "b.jar"

    def test_falls_back_to_any_server_download(self) -> None:
        build = BuildInfo(
            project="paper",
            version="1.21.4",
            build=1,
            downloads={"myserverthing": DownloadInfo("c.jar", "https://c")},
        )
        assert build.server_download.name == "c.jar"

    def test_missing_downloads_raise(self) -> None:
        build = BuildInfo(project="paper", version="1.21.4", build=1)
        with pytest.raises(ValidationError):
            _ = build.server_download


class TestJavaInstall:
    def test_round_trip(self) -> None:
        install = JavaInstall(
            major=21,
            version="21.0.4+7",
            path=r"C:\java\bin\java.exe",
            home=r"C:\java",
            os="windows",
            arch="x64",
            installed_at="2026-01-01T00:00:00+00:00",
        )
        assert JavaInstall.from_dict(install.to_dict()) == install
        assert install.executable == install.path
