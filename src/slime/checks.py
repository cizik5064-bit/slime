"""Environment checks used by ``slime doctor`` and the TUI."""

from __future__ import annotations

import platform
import shutil
import socket
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import psutil

from .config import Config
from .java import JavaManager
from .models import Server
from .store import ServerStore

GIB = 1024**3


class CheckStatus(StrEnum):
    OK = "ok"
    INFO = "info"
    WARN = "warn"
    FAIL = "fail"


@dataclass(slots=True)
class CheckResult:
    id: str
    title: str
    status: CheckStatus
    message: str
    hint: str | None = None
    scope: str = "global"


def _result(
    check_id: str,
    title: str,
    status: CheckStatus,
    message: str,
    *,
    hint: str | None = None,
    scope: str = "global",
) -> CheckResult:
    return CheckResult(check_id, title, status, message, hint, scope)


def check_python() -> CheckResult:
    version = sys.version_info
    if version >= (3, 11):
        return _result(
            "python",
            "Python",
            CheckStatus.OK,
            f"Python {version.major}.{version.minor}.{version.micro}",
        )
    return _result(
        "python",
        "Python",
        CheckStatus.FAIL,
        f"Python {version.major}.{version.minor} is too old.",
        hint="Slime requires Python 3.11 or newer.",
    )


def check_os() -> CheckResult:
    system = platform.system()
    if system == "Windows":
        release = platform.release()
        try:
            major = int(platform.version().split(".")[0])
        except (ValueError, IndexError):
            major = 0
        if major >= 10:
            return _result("os", "Operating system", CheckStatus.OK, f"Windows {release}")
        return _result(
            "os",
            "Operating system",
            CheckStatus.FAIL,
            f"Windows {release} is not supported by this build.",
            hint="Slime requires Windows 10 or newer. Windows 7/8.1 needs a legacy build.",
        )
    if system in {"Linux", "Darwin"}:
        return _result("os", "Operating system", CheckStatus.OK, f"{system} {platform.release()}")
    return _result(
        "os",
        "Operating system",
        CheckStatus.WARN,
        f"Untested platform: {system}",
        hint="Slime targets Windows 10+ and Linux; other platforms may work.",
    )


def check_home_writable(config: Config) -> CheckResult:
    probe = config.paths.home / ".write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return _result(
            "home",
            "Slime home",
            CheckStatus.FAIL,
            f"Cannot write to {config.paths.home}: {exc}",
            hint="Set SLIME_HOME to a writable directory.",
        )
    return _result("home", "Slime home", CheckStatus.OK, str(config.paths.home))


def check_disk(config: Config, *, path: Path | None = None) -> CheckResult:
    target = path or config.paths.home
    try:
        free = shutil.disk_usage(target).free
    except OSError as exc:
        return _result(
            "disk",
            "Disk space",
            CheckStatus.WARN,
            f"Cannot read disk usage for {target}: {exc}",
            scope="global" if path is None else "server",
        )
    free_gib = free / GIB
    if free < 1 * GIB:
        return _result(
            "disk",
            "Disk space",
            CheckStatus.FAIL,
            f"Only {free_gib:.1f} GiB free on {target}.",
            hint="Free at least 1 GiB; worlds and backups grow quickly.",
            scope="global" if path is None else "server",
        )
    if free < 5 * GIB:
        return _result(
            "disk",
            "Disk space",
            CheckStatus.WARN,
            f"{free_gib:.1f} GiB free on {target}.",
            hint="Consider freeing space; large worlds can exceed this.",
            scope="global" if path is None else "server",
        )
    return _result(
        "disk",
        "Disk space",
        CheckStatus.OK,
        f"{free_gib:.1f} GiB free on {target}",
        scope="global" if path is None else "server",
    )


def port_available(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def check_port(server: Server, *, running: bool = False) -> CheckResult:
    if running:
        return _result(
            "port",
            "Port",
            CheckStatus.OK,
            f"Port {server.port} is used by this server.",
            scope="server",
        )
    if port_available(server.port):
        return _result(
            "port",
            "Port",
            CheckStatus.OK,
            f"Port {server.port} is free",
            scope="server",
        )
    return _result(
        "port",
        "Port",
        CheckStatus.FAIL,
        f"Port {server.port} is already in use.",
        hint="Stop the other process or change the port in server.properties / slime.json.",
        scope="server",
    )


def check_memory(server: Server) -> CheckResult:
    memory = psutil.virtual_memory()
    configured = server.memory_mb * 1024 * 1024
    available_gib = memory.available / GIB
    configured_gib = server.memory_mb / 1024
    if configured > memory.total:
        return _result(
            "memory",
            "Memory",
            CheckStatus.FAIL,
            f"{configured_gib:.1f} GiB requested, but the machine has "
            f"{memory.total / GIB:.1f} GiB.",
            hint="Lower the server memory: edit memory_mb in slime.json.",
            scope="server",
        )
    if configured > memory.available:
        return _result(
            "memory",
            "Memory",
            CheckStatus.WARN,
            f"{configured_gib:.1f} GiB requested, but only {available_gib:.1f} GiB "
            "is currently available.",
            hint="Close other applications or lower the server memory.",
            scope="server",
        )
    return _result(
        "memory",
        "Memory",
        CheckStatus.OK,
        f"{configured_gib:.1f} GiB configured, {available_gib:.1f} GiB available",
        scope="server",
    )


def check_java(server: Server, java_manager: JavaManager) -> CheckResult:
    install = java_manager.find_for(server)
    if install is None:
        return _result(
            "java",
            "Java",
            CheckStatus.FAIL,
            f"Java {server.java_major} was not found.",
            hint=f"Install it with: slime java install {server.java_major}",
            scope="server",
        )
    if install.major != server.java_major:
        return _result(
            "java",
            "Java",
            CheckStatus.FAIL,
            f"Java {install.major} found, but Java {server.java_major} is required.",
            hint=f"Install it with: slime java install {server.java_major}",
            scope="server",
        )
    return _result(
        "java",
        "Java",
        CheckStatus.OK,
        f"Java {install.major} ({install.version or 'unknown version'})",
        scope="server",
    )


def check_jar(server: Server, store: ServerStore) -> CheckResult:
    jar = store.path(server.name) / server.jar_file
    if jar.is_file():
        size_mib = jar.stat().st_size / (1024 * 1024)
        return _result(
            "jar",
            "Server jar",
            CheckStatus.OK,
            f"{jar.name} ({size_mib:.1f} MiB)",
            scope="server",
        )
    return _result(
        "jar",
        "Server jar",
        CheckStatus.FAIL,
        f"Missing {jar}.",
        hint="Recreate the server or download the jar manually.",
        scope="server",
    )


def check_eula(server: Server, store: ServerStore) -> CheckResult:
    if server.is_proxy:
        return _result(
            "eula",
            "EULA",
            CheckStatus.INFO,
            "Not required for proxies.",
            scope="server",
        )
    from .properties import read_eula

    if server.eula_accepted and read_eula(store.path(server.name) / "eula.txt"):
        return _result(
            "eula",
            "EULA",
            CheckStatus.OK,
            "Accepted",
            scope="server",
        )
    return _result(
        "eula",
        "EULA",
        CheckStatus.FAIL,
        "The Minecraft EULA has not been accepted.",
        hint="Read https://aka.ms/MinecraftEULA, then run: "
        f"slime server eula {server.name} --accept",
        scope="server",
    )


def check_properties_port(server: Server, store: ServerStore) -> CheckResult:
    if server.is_proxy:
        return _result(
            "properties",
            "Configuration",
            CheckStatus.INFO,
            "Proxy configuration is generated on first start.",
            scope="server",
        )
    from .properties import read_properties

    path = store.path(server.name) / "server.properties"
    if not path.is_file():
        return _result(
            "properties",
            "Configuration",
            CheckStatus.WARN,
            "server.properties is missing; it will be generated on first start.",
            scope="server",
        )
    configured = read_properties(path).get("server-port")
    if configured is None:
        return _result(
            "properties",
            "Configuration",
            CheckStatus.WARN,
            f"server.properties does not set server-port; slime.json says port {server.port}.",
            hint="Add server-port to server.properties, or align slime.json with the "
            "game's default of 25565.",
            scope="server",
        )
    if configured == str(server.port):
        return _result(
            "properties",
            "Configuration",
            CheckStatus.OK,
            f"server-port={configured}",
            scope="server",
        )
    return _result(
        "properties",
        "Configuration",
        CheckStatus.WARN,
        f"slime.json says port {server.port}, server.properties says {configured}.",
        hint="Align both values to avoid connecting to the wrong port.",
        scope="server",
    )


def run_checks(
    config: Config,
    store: ServerStore,
    java_manager: JavaManager,
    *,
    server: Server | None = None,
) -> list[CheckResult]:
    """Run global checks and, optionally, checks for one server."""
    results = [
        check_python(),
        check_os(),
        check_home_writable(config),
        check_disk(config),
    ]

    if server is None:
        servers = store.list()
        if not servers:
            results.append(
                _result(
                    "servers",
                    "Servers",
                    CheckStatus.INFO,
                    "No servers configured yet.",
                    hint="Create one with: slime server create my-server --accept-eula",
                )
            )
        else:
            results.append(
                _result(
                    "servers",
                    "Servers",
                    CheckStatus.OK,
                    f"{len(servers)} configured",
                )
            )
        results.append(
            _result(
                "java",
                "Java runtimes",
                CheckStatus.INFO,
                f"{len(java_manager.installed())} installed by Slime",
                hint="Install one with: slime java install 21",
            )
        )
        return results

    running, _pid = store.is_running(server.name)
    results += [
        check_jar(server, store),
        check_java(server, java_manager),
        check_eula(server, store),
        check_properties_port(server, store),
        check_port(server, running=running),
        check_memory(server),
        check_disk(config, path=store.path(server.name)),
    ]
    for result in results[-7:]:
        result.scope = "server"
    return results


def summarize(results: list[CheckResult]) -> dict[CheckStatus, int]:
    counts = {status: 0 for status in CheckStatus}
    for result in results:
        counts[result.status] += 1
    return counts


def has_failures(results: list[CheckResult]) -> bool:
    return any(result.status is CheckStatus.FAIL for result in results)
