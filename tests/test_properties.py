from __future__ import annotations

from pathlib import Path

from slime.properties import (
    EULA_HEADER,
    ensure_server_properties,
    format_properties,
    parse_properties,
    read_eula,
    read_properties,
    write_eula,
    write_properties,
)


def test_parse_basic_properties() -> None:
    text = """
    # comment
    ! another comment
    server-port=25565
    motd: Hello
    online-mode true
    spaced = value
    """
    values = parse_properties(text)
    assert values == {
        "server-port": "25565",
        "motd": "Hello",
        "online-mode": "true",
        "spaced": "value",
    }


def test_parse_escapes_and_unicode() -> None:
    text = r"""
    key\ with\ space=a\=b\:c
    tab=one\ttwo
    newline=one\ntwo
    unicode=\u00e9
    """
    values = parse_properties(text)
    assert values["key with space"] == "a=b:c"
    assert values["tab"] == "one\ttwo"
    assert values["newline"] == "one\ntwo"
    assert values["unicode"] == "é"


def test_format_properties_round_trip() -> None:
    values = {
        "server-port": "25565",
        "motd": "Hello: world = ok",
        "key with space": "value with space",
        "backslash": r"C:\server",
        "tab": "a\tb",
    }
    text = format_properties(values, header="# header")
    assert text.startswith("# header\n")
    assert parse_properties(text) == values


def test_write_properties_merges_by_default(tmp_path: Path) -> None:
    path = tmp_path / "server.properties"
    path.write_text("server-port=25565\nmotd=Old\n", encoding="utf-8")
    result = write_properties(path, {"motd": "New", "max-players": "10"})
    assert result == {
        "server-port": "25565",
        "motd": "New",
        "max-players": "10",
    }
    assert read_properties(path) == result


def test_write_properties_can_replace(tmp_path: Path) -> None:
    path = tmp_path / "server.properties"
    path.write_text("old=1\n", encoding="utf-8")
    write_properties(path, {"new": "2"}, merge=False)
    assert read_properties(path) == {"new": "2"}


def test_ensure_server_properties_creates_defaults(tmp_path: Path) -> None:
    path = tmp_path / "server.properties"
    values = ensure_server_properties(path, port=25566, motd="Hi", max_players=5)
    assert values["server-port"] == "25566"
    assert values["motd"] == "Hi"
    assert values["max-players"] == "5"
    assert values["online-mode"] == "true"
    assert path.is_file()


def test_ensure_server_properties_preserves_existing_values(tmp_path: Path) -> None:
    path = tmp_path / "server.properties"
    path.write_text("server-port=25565\nmotd=Custom\n", encoding="utf-8")
    values = ensure_server_properties(path, port=25566, motd="Generated")
    assert values["server-port"] == "25565"
    assert values["motd"] == "Custom"


def test_eula_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "eula.txt"
    write_eula(path, accepted=True)
    assert path.read_text(encoding="utf-8").startswith(EULA_HEADER)
    assert read_eula(path) is True

    write_eula(path, accepted=False)
    assert read_eula(path) is False


def test_read_missing_files_are_empty(tmp_path: Path) -> None:
    assert read_properties(tmp_path / "missing.properties") == {}
    assert read_eula(tmp_path / "missing-eula.txt") is False
