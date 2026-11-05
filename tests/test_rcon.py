"""Tests for the Source RCON client and server.properties helpers."""

from __future__ import annotations

import socket
import struct
import threading
from pathlib import Path

import pytest

from slime.errors import RconError
from slime.models import Server
from slime.properties import read_properties
from slime.rcon import (
    DEFAULT_RCON_PORT,
    RconClient,
    RconConfig,
    ensure_rcon_config,
    read_rcon_config,
    require_rcon_config,
    shutdown_command,
)


def make_server(project: str = "paper") -> Server:
    return Server(
        name="survival",
        project=project,
        minecraft_version="1.21.4",
        build=232,
        java_major=21,
        memory_mb=2048,
        port=25565,
    )


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def write_properties(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_ensure_rcon_config_fills_missing_values(tmp_path: Path) -> None:
    directory = tmp_path / "server"
    directory.mkdir()
    write_properties(directory / "server.properties", "motd=Hello\n")

    config = ensure_rcon_config(directory, 25565)

    assert config is not None
    assert config.host == "127.0.0.1"
    assert config.port == 25575
    assert len(config.password) >= 16

    values = read_properties(directory / "server.properties")
    assert values["enable-rcon"] == "true"
    assert values["rcon.port"] == "25575"
    assert values["rcon.password"] == config.password
    assert values["motd"] == "Hello"
    assert read_rcon_config(directory) == config


def test_ensure_rcon_config_uses_fallback_port(tmp_path: Path) -> None:
    directory = tmp_path / "server"
    directory.mkdir()
    write_properties(directory / "server.properties", "server-port=65530\n")

    config = ensure_rcon_config(directory, 65530)

    assert config is not None
    assert config.port == DEFAULT_RCON_PORT


def test_ensure_rcon_config_preserves_explicit_values(tmp_path: Path) -> None:
    directory = tmp_path / "server"
    directory.mkdir()
    write_properties(
        directory / "server.properties",
        "enable-rcon=true\nrcon.port=25600\nrcon.password=existing\n",
    )

    config = ensure_rcon_config(directory, 25565)

    assert config == RconConfig("127.0.0.1", 25600, "existing")
    values = read_properties(directory / "server.properties")
    assert values["rcon.port"] == "25600"
    assert values["rcon.password"] == "existing"


def test_ensure_rcon_config_respects_explicit_disable(tmp_path: Path) -> None:
    directory = tmp_path / "server"
    directory.mkdir()
    write_properties(directory / "server.properties", "enable-rcon=false\n")

    assert ensure_rcon_config(directory, 25565) is None
    values = read_properties(directory / "server.properties")
    assert values["enable-rcon"] == "false"
    assert "rcon.password" not in values


def test_ensure_rcon_config_replaces_port_equal_to_server_port(tmp_path: Path) -> None:
    directory = tmp_path / "server"
    directory.mkdir()
    write_properties(
        directory / "server.properties",
        "enable-rcon=true\nrcon.port=25565\nrcon.password=secret\n",
    )

    config = ensure_rcon_config(directory, 25565)

    assert config is not None
    assert config.port == 25575


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "enable-rcon=false\nrcon.port=25575\nrcon.password=x\n",
        "enable-rcon=true\nrcon.password=x\n",
        "enable-rcon=true\nrcon.port=not-a-port\nrcon.password=x\n",
        "enable-rcon=true\nrcon.port=70000\nrcon.password=x\n",
        "enable-rcon=true\nrcon.port=25575\n",
    ],
)
def test_read_rcon_config_returns_none_when_disabled_or_invalid(
    tmp_path: Path, contents: str
) -> None:
    directory = tmp_path / "server"
    directory.mkdir()
    write_properties(directory / "server.properties", contents)

    assert read_rcon_config(directory) is None
    with pytest.raises(RconError, match="RCON is not enabled"):
        require_rcon_config(directory)


def test_require_rcon_config_returns_settings(tmp_path: Path) -> None:
    directory = tmp_path / "server"
    directory.mkdir()
    write_properties(
        directory / "server.properties",
        "enable-rcon=true\nrcon.port=25575\nrcon.password=secret\n",
    )

    config = require_rcon_config(directory)

    assert config == RconConfig("127.0.0.1", 25575, "secret")
    assert config.address == "127.0.0.1:25575"


@pytest.mark.parametrize(
    ("project", "expected"),
    [("paper", "stop"), ("folia", "stop"), ("velocity", "shutdown"), ("waterfall", "end")],
)
def test_shutdown_command_depends_on_project(project: str, expected: str) -> None:
    assert shutdown_command(make_server(project)) == expected


# ---------------------------------------------------------------------------
# Wire protocol
# ---------------------------------------------------------------------------

_TYPE_RESPONSE = 0
_TYPE_AUTH_RESPONSE = 2
_TYPE_COMMAND = 2
_TYPE_AUTH = 3


def _recv_exact(conn: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = conn.recv(remaining)
        if not chunk:
            raise OSError("closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_packet(conn: socket.socket) -> tuple[int, int, bytes]:
    raw_length = _recv_exact(conn, 4)
    (length,) = struct.unpack("<i", raw_length)
    data = _recv_exact(conn, length)
    request_id, packet_type = struct.unpack("<ii", data[:8])
    return request_id, packet_type, data[8:-2]


def _send_packet(
    conn: socket.socket, request_id: int, packet_type: int, payload: bytes
) -> None:
    body = struct.pack("<ii", request_id, packet_type) + payload + b"\x00\x00"
    conn.sendall(struct.pack("<i", len(body)) + body)


class FakeRconServer:
    """A tiny in-process RCON server for client tests."""

    def __init__(
        self,
        password: str = "secret",
        *,
        responses: dict[str, list[str]] | None = None,
        authenticate: bool = True,
    ) -> None:
        self.password = password
        self.responses = responses or {}
        self.authenticate = authenticate
        self.error: Exception | None = None
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self.port = self._listener.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> FakeRconServer:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._listener.close()
        self._thread.join(timeout=3)

    def config(self) -> RconConfig:
        return RconConfig("127.0.0.1", self.port, self.password)

    def _serve(self) -> None:
        try:
            connection, _address = self._listener.accept()
            with connection:
                request_id, packet_type, payload = _read_packet(connection)
                if packet_type != _TYPE_AUTH or payload.decode() != self.password:
                    _send_packet(connection, -1, _TYPE_AUTH_RESPONSE, b"")
                    return
                if not self.authenticate:
                    _send_packet(connection, -1, _TYPE_AUTH_RESPONSE, b"")
                    return
                _send_packet(connection, request_id, _TYPE_AUTH_RESPONSE, b"")
                while True:
                    try:
                        request_id, packet_type, payload = _read_packet(connection)
                    except (OSError, struct.error):
                        return
                    if packet_type != _TYPE_COMMAND:
                        continue
                    command = payload.decode()
                    chunks = self.responses.get(command, [""])
                    for chunk in chunks:
                        _send_packet(connection, request_id, _TYPE_RESPONSE, chunk.encode())
                    if command == "stop":
                        return
        except Exception as exc:  # pragma: no cover - surfaced by asserts
            self.error = exc


def test_client_authenticates_and_returns_a_response() -> None:
    with FakeRconServer(responses={"list": ["There are 0 players."]}) as server:
        with RconClient(server.config(), timeout=3) as client:
            assert client.command("list") == "There are 0 players."
        assert server.error is None


def test_client_joins_multi_packet_responses() -> None:
    with FakeRconServer(
        responses={"say hello": ["hello ", "from ", "RCON"]}
    ) as server:
        client = RconClient(server.config(), timeout=3)
        try:
            assert client.command("say hello") == "hello from RCON"
        finally:
            client.close()


def test_client_rejects_a_bad_password() -> None:
    with FakeRconServer(password="correct") as server, pytest.raises(
        RconError, match="authentication"
    ):
        RconClient(
            RconConfig("127.0.0.1", server.port, "wrong"), timeout=3
        ).connect()


def test_client_reports_a_connection_error() -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    client = RconClient(RconConfig("127.0.0.1", port, "secret"), timeout=1)
    with pytest.raises(RconError, match="Could not connect"):
        client.connect()
    client.close()


def test_empty_command_does_not_touch_the_socket() -> None:
    client = RconClient(RconConfig("127.0.0.1", 1, "secret"), timeout=1)
    assert client.command("   ") == ""
