"""Temurin JDK installation and discovery."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .api.adoptium import AdoptiumClient, current_arch, current_os
from .config import Config
from .errors import JavaError
from .models import JavaInstall, Server
from .utils.archives import extract_archive, find_java_executable
from .utils.downloads import download_file

DownloadProgress = Callable[[int, int | None], None]
METADATA_FILE = "slime-java.json"
_JAVA_VERSION_RE = re.compile(r'java\.version\s*=\s*"?([^"\s]+)"?')
_JAVA_HOME_RE = re.compile(r'java\.home\s*=\s*"?([^"\n]+)"?')


def _java_major(version: str) -> int | None:
    version = version.strip()
    if not version:
        return None
    if version.startswith("1."):
        parts = version.split(".")
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    match = re.match(r"^(\d+)", version)
    return int(match.group(1)) if match else None


class JavaManager:
    """Manage Temurin runtimes under ``~/.slime/java``."""

    def __init__(self, config: Config, client: AdoptiumClient | None = None) -> None:
        self.config = config
        self.paths = config.paths
        self.client = client or AdoptiumClient(
            config.settings.adoptium_base_url,
            user_agent=config.settings.user_agent,
            timeout=config.settings.request_timeout,
        )

    # ---------------------------------------------------------------- installed
    def installed(self) -> list[JavaInstall]:
        """Return every JDK installed by Slime, newest major last."""
        result: dict[int, JavaInstall] = {}
        if not self.paths.java.exists():
            return []
        for directory in sorted(self.paths.java.iterdir()):
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            install = self._load_install(directory)
            if install is not None:
                result.setdefault(install.major, install)
        return [result[major] for major in sorted(result)]

    def get(self, major: int) -> JavaInstall | None:
        for install in self.installed():
            if install.major == major:
                return install
        return None

    def _load_install(self, directory: Path) -> JavaInstall | None:
        metadata = directory / METADATA_FILE
        executable_name = "java.exe" if os.name == "nt" else "java"
        fallback = directory / "bin" / executable_name
        if metadata.is_file():
            try:
                data = json.loads(metadata.read_text(encoding="utf-8"))
                install = JavaInstall.from_dict(data)
                if Path(install.path).is_file():
                    return install
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if fallback.is_file():
            match = re.search(r"temurin-(\d+)-", directory.name)
            major = int(match.group(1)) if match else None
            if major is None:
                inspected = self.inspect(fallback)
                if inspected is not None:
                    return inspected
                return None
            return JavaInstall(
                major=major,
                version="",
                path=str(fallback),
                home=str(directory),
                source="temurin",
                os=current_os(),
                arch=current_arch(),
            )
        return None

    # ------------------------------------------------------------------ install
    def install(
        self,
        major: int,
        *,
        os_name: str | None = None,
        arch: str | None = None,
        force: bool = False,
        progress: DownloadProgress | None = None,
    ) -> JavaInstall:
        """Download and unpack a Temurin JDK for the current platform."""
        existing = self.get(major)
        if existing is not None and not force:
            return existing

        os_name = (os_name or current_os()).lower()
        arch = (arch or current_arch()).lower()
        package = self.client.latest_package(major, os_name=os_name, arch=arch)
        archive = self.paths.cache / package.name
        download_file(
            package.url,
            archive,
            sha256=package.sha256,
            size=package.size,
            user_agent=self.config.settings.user_agent,
            timeout=max(self.config.settings.request_timeout, 60.0),
            progress=progress,
        )

        staging = self.paths.java / f".staging-{uuid.uuid4().hex}"
        final = self.paths.java / f"temurin-{major}-{os_name}-{arch}"
        try:
            extract_archive(archive, staging)
            executable = find_java_executable(staging)
            if executable is None:
                raise JavaError(
                    "The Temurin archive did not contain a Java executable.",
                    hint="Try again; if it persists, install Java manually.",
                )
            java_home = executable.parent.parent
            if final.exists():
                if not force:
                    raise JavaError(
                        f"A Java {major} runtime already exists at {final}.",
                        hint="Use --force to reinstall it.",
                    )
                shutil.rmtree(final)
            shutil.move(str(java_home), str(final))
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            archive.unlink(missing_ok=True)
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

        executable = final / "bin" / ("java.exe" if os.name == "nt" else "java")
        if not executable.is_file():
            raise JavaError(
                f"Java was extracted to {final}, but {executable.name} is missing.",
                hint="Delete the directory and reinstall: slime java install "
                f"{major} --force",
            )
        if os.name != "nt":
            executable.chmod(0o755)

        inspected = self.inspect(executable)
        install = JavaInstall(
            major=major,
            version=inspected.version if inspected else package.version,
            path=str(executable),
            home=str(final),
            source="temurin",
            os=os_name,
            arch=arch,
            installed_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        metadata = final / METADATA_FILE
        metadata.write_text(
            json.dumps(install.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
        return install

    # ------------------------------------------------------------------- remove
    def remove(self, major: int) -> bool:
        install = self.get(major)
        if install is None:
            return False
        home = Path(install.home)
        java_root = self.paths.java.resolve()
        try:
            home.resolve().relative_to(java_root)
        except ValueError as exc:
            raise JavaError(
                f"Refusing to delete {home}: it is outside Slime's Java directory."
            ) from exc
        shutil.rmtree(home)
        return True

    # ------------------------------------------------------------------ inspect
    def inspect(self, executable: str | Path) -> JavaInstall | None:
        executable = Path(executable)
        if not executable.is_file():
            return None
        try:
            completed = subprocess.run(
                [str(executable), "-XshowSettings:properties", "-version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        version_match = _JAVA_VERSION_RE.search(output)
        home_match = _JAVA_HOME_RE.search(output)
        version = version_match.group(1) if version_match else ""
        major = _java_major(version)
        if major is None:
            return None
        return JavaInstall(
            major=major,
            version=version,
            path=str(executable),
            home=home_match.group(1).strip() if home_match else str(executable.parent.parent),
            source="system",
        )

    def system_java(self) -> JavaInstall | None:
        """Locate a ``java`` executable on PATH or via ``JAVA_HOME``."""
        candidates: list[Path] = []
        java_home = os.environ.get("JAVA_HOME")
        if java_home:
            candidates.append(Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java"))
        found = shutil.which("java")
        if found:
            candidates.append(Path(found))
        for candidate in candidates:
            install = self.inspect(candidate)
            if install is not None:
                return install
        return None

    # -------------------------------------------------------------------- find
    def find_for(self, server: Server) -> JavaInstall | None:
        """Resolve the Java runtime a server should use."""
        if server.java_path:
            install = self.inspect(server.java_path)
            if install is not None and install.major == server.java_major:
                return install
            return None
        managed = self.get(server.java_major)
        if managed is not None:
            return managed
        system = self.system_java()
        if system is not None and system.major == server.java_major:
            return system
        return None

    def require_for(self, server: Server) -> JavaInstall:
        install = self.find_for(server)
        if install is not None:
            return install
        if server.java_path:
            raise JavaError(
                f"The configured Java path does not exist or is not Java {server.java_major}: "
                f"{server.java_path}",
                hint=f"Install it with: slime java install {server.java_major} --force",
            )
        raise JavaError(
            f"Java {server.java_major} is required by {server.name} "
            f"({server.project.display_name} {server.minecraft_version}), but it is not installed.",
            hint=f"Install it with: slime java install {server.java_major}",
        )
