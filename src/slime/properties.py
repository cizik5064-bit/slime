"""Minimal, dependency-free reader/writer for Java ``.properties`` files.

Minecraft uses Java properties for ``server.properties``. The format is not
quite JSON: keys and values are separated by ``=``, ``:`` or whitespace, and
backslash escapes are supported. Slime only needs a faithful subset, but the
implementation below handles the common escapes and preserves unknown keys.
"""

from __future__ import annotations

from pathlib import Path

EULA_HEADER = (
    "#By changing the setting below to TRUE you are indicating your agreement "
    "to our EULA (https://aka.ms/MinecraftEULA).\n"
)

DEFAULT_SERVER_PROPERTIES: dict[str, str] = {
    "server-port": "25565",
    "motd": "A Minecraft server managed by Slime",
    "online-mode": "true",
    "max-players": "20",
    "view-distance": "10",
    "simulation-distance": "10",
    "enable-command-block": "false",
    "spawn-protection": "16",
}


def _unescape(text: str) -> str:
    result: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char != "\\" or index + 1 >= length:
            result.append(char)
            index += 1
            continue
        index += 1
        escaped = text[index]
        index += 1
        if escaped == "t":
            result.append("\t")
        elif escaped == "n":
            result.append("\n")
        elif escaped == "r":
            result.append("\r")
        elif escaped == "f":
            result.append("\f")
        elif escaped == "u" and index + 4 <= length:
            code = text[index : index + 4]
            try:
                result.append(chr(int(code, 16)))
                index += 4
            except ValueError:
                result.append("\\u" + code)
                index += 4
        else:
            result.append(escaped)
    return "".join(result)


def _escape(text: str, *, is_key: bool = False) -> str:
    result: list[str] = []
    for position, char in enumerate(text):
        if char == "\\":
            result.append("\\\\")
        elif char == "\n":
            result.append("\\n")
        elif char == "\r":
            result.append("\\r")
        elif char == "\t":
            result.append("\\t")
        elif char in "=:" or (is_key and char in " #!"):
            result.append("\\" + char)
        elif char == " " and (is_key or position == 0):
            result.append("\\ ")
        else:
            result.append(char)
    return "".join(result)


def _split_line(line: str) -> tuple[str, str] | None:
    """Split ``key=value`` at the first unescaped separator."""
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in "=:":
            return line[:index], line[index + 1 :]
        if char in " \t\f":
            key = line[:index]
            remainder = line[index:].lstrip(" \t\f")
            if remainder.startswith(("=", ":")):
                remainder = remainder[1:]
            return key, remainder
    return None


def parse_properties(text: str) -> dict[str, str]:
    """Parse properties text into an ordered mapping (comments are dropped)."""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        split = _split_line(raw_line.lstrip(" \t\f"))
        if split is None:
            continue
        key, value = split
        key = _unescape(key.strip())
        value = _unescape(value.strip())
        if key:
            values[key] = value
    return values


def read_properties(path: Path) -> dict[str, str]:
    try:
        return parse_properties(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}


def format_properties(values: dict[str, str], *, header: str | None = None) -> str:
    lines: list[str] = []
    if header:
        lines.extend(header.rstrip("\n").splitlines())
    for key, value in values.items():
        lines.append(f"{_escape(str(key), is_key=True)}={_escape(str(value))}")
    return "\n".join(lines) + "\n"


def write_properties(
    path: Path,
    values: dict[str, str],
    *,
    header: str | None = None,
    merge: bool = True,
) -> dict[str, str]:
    """Write properties, optionally preserving keys already in the file."""
    existing = read_properties(path) if merge and path.exists() else {}
    existing.update({str(key): str(value) for key, value in values.items()})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_properties(existing, header=header), encoding="utf-8", newline="\n")
    return existing


def ensure_server_properties(
    path: Path,
    *,
    port: int,
    motd: str = "A Minecraft server managed by Slime",
    online_mode: bool = True,
    max_players: int = 20,
) -> dict[str, str]:
    """Create ``server.properties`` with sensible defaults.

    Existing keys are never overwritten, so re-running this is safe.
    """
    desired = dict(DEFAULT_SERVER_PROPERTIES)
    desired.update(
        {
            "server-port": str(port),
            "motd": motd,
            "online-mode": "true" if online_mode else "false",
            "max-players": str(max_players),
        }
    )
    existing = read_properties(path) if path.exists() else {}
    merged = {**desired, **existing}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        format_properties(merged, header="#Minecraft server properties\n#Generated by Slime"),
        encoding="utf-8",
        newline="\n",
    )
    return merged


def write_eula(path: Path, accepted: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        EULA_HEADER + f"eula={'true' if accepted else 'false'}\n",
        encoding="utf-8",
        newline="\n",
    )


def read_eula(path: Path) -> bool:
    return read_properties(path).get("eula", "false").strip().lower() == "true"
