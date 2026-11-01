"""Client for the Eclipse Adoptium (Temurin) API v3.

Documentation: https://api.adoptium.net/q/swagger-ui/

Slime downloads the *archive* package (zip on Windows, tar.gz on Linux/macOS)
rather than the installer, extracts it into ``~/.slime/java`` and records the
exact ``bin/java`` path for each server.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Any

import httpx

from .. import __version__
from ..errors import ApiError

DEFAULT_BASE_URL = "https://api.adoptium.net/v3"

#: Adoptium's platform identifiers.
_OS_ALIASES = {
    "windows": "windows",
    "win32": "windows",
    "cygwin": "windows",
    "linux": "linux",
    "darwin": "mac",
    "macos": "mac",
    "mac": "mac",
}
_ARCH_ALIASES = {
    "amd64": "x64",
    "x86_64": "x64",
    "x64": "x64",
    "i386": "x86",
    "i686": "x86",
    "x86": "x86",
    "aarch64": "aarch64",
    "arm64": "aarch64",
    "armv7l": "arm",
    "ppc64le": "ppc64le",
    "s390x": "s390x",
    "riscv64": "riscv64",
}


def current_os() -> str:
    system = platform.system().lower()
    return _OS_ALIASES.get(system, system)


def current_arch() -> str:
    machine = platform.machine().lower()
    return _ARCH_ALIASES.get(machine, machine)


@dataclass(slots=True)
class JavaPackage:
    """A downloadable Temurin JDK archive."""

    major: int
    version: str
    os: str
    arch: str
    name: str
    url: str
    sha256: str | None = None
    size: int | None = None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class AdoptiumClient:
    """Thin synchronous client around the Adoptium v3 API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        user_agent: str = f"Slime/{__version__}",
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self._client = client or httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> AdoptiumClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ApiError(
                f"Could not reach the Adoptium API: {exc}",
                hint="Check your internet connection or try again in a minute.",
            ) from exc
        if response.status_code == 404:
            raise ApiError(
                f"Adoptium has no package for this request ({path}).",
                hint="The requested Java version may not exist for your platform.",
            )
        if response.status_code >= 400:
            raise ApiError(
                f"Adoptium API returned HTTP {response.status_code} for {path}."
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError("Adoptium API returned invalid JSON.") from exc

    # --------------------------------------------------------------- metadata
    def available_releases(self) -> dict[str, Any]:
        data = self._get("info/available_releases")
        if not isinstance(data, dict):
            raise ApiError("Adoptium API returned an unexpected release list.")
        return data

    def releases(self) -> list[int]:
        data = self.available_releases()
        raw = data.get("available_releases") or []
        releases = sorted(
            {int(value) for value in raw if _as_int(value) is not None}
        )
        if not releases:
            raise ApiError("Adoptium API returned no available Java releases.")
        return releases

    def lts_releases(self) -> list[int]:
        data = self.available_releases()
        raw = data.get("available_lts_releases") or []
        return sorted({int(value) for value in raw if _as_int(value) is not None})

    # --------------------------------------------------------------- packages
    def latest_package(
        self,
        major: int,
        *,
        os_name: str | None = None,
        arch: str | None = None,
    ) -> JavaPackage:
        os_name = (os_name or current_os()).lower()
        arch = (arch or current_arch()).lower()
        params = {
            "architecture": arch,
            "image_type": "jdk",
            "os": os_name,
            "vendor": "eclipse",
            "project": "jdk",
        }
        data = self._get(f"assets/latest/{int(major)}/hotspot", params=params)
        assets = data if isinstance(data, list) else data.get("assets", [])
        if not isinstance(assets, list) or not assets:
            raise ApiError(
                f"No Temurin JDK {major} package found for {os_name}/{arch}.",
                hint="Run `slime java releases` to see supported versions, or install Java manually.",
            )

        for asset in assets:
            if not isinstance(asset, dict):
                continue
            binary = asset.get("binary") or {}
            package = binary.get("package") or {}
            link = package.get("link")
            if not link:
                continue
            checksum = package.get("checksum")
            if isinstance(checksum, dict):
                checksum = checksum.get("checksum") or checksum.get("value")
            version = (
                (asset.get("version") or {}).get("semver")
                or (asset.get("release") or {}).get("version", {}).get("semver")
                or (asset.get("version") or {}).get("openjdk_version")
                or str(major)
            )
            return JavaPackage(
                major=int(major),
                version=str(version),
                os=str(binary.get("os") or os_name),
                arch=str(binary.get("architecture") or arch),
                name=str(package.get("name") or f"temurin-{major}.zip"),
                url=str(link),
                sha256=str(checksum) if checksum else None,
                size=_as_int(package.get("size")),
            )

        raise ApiError(
            f"Adoptium returned assets for Java {major}, but none had an archive package.",
            hint="Try again later or install Java manually.",
        )
