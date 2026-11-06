"""Client for the Hangar API v1.

Hangar hosts Paper, Velocity and Waterfall plugins. Search and version
endpoints accept a platform and a Minecraft version, so Slime asks the server
only for compatible content and re-checks the result locally.

Documentation: https://hangar.papermc.io/api-docs
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from .. import __version__
from ..errors import ApiError
from ..models import (
    ContentDependency,
    ContentHit,
    ContentKind,
    ContentSource,
    ContentVersion,
)

DEFAULT_BASE_URL = "https://hangar.papermc.io/api/v1"


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _supports(value: Any, platform: str, game_version: str) -> bool:
    """Check a Hangar ``supportedPlatforms`` map without over-filtering."""
    if not isinstance(value, dict):
        return True
    versions = value.get(platform.upper())
    if not isinstance(versions, list):
        return False
    return game_version in {str(version) for version in versions}


class HangarClient:
    """Thin synchronous client around the Hangar API v1."""

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

    # ------------------------------------------------------------------ http
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> HangarClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ApiError(
                f"Could not reach Hangar: {exc}",
                hint="Check your internet connection or try again in a minute.",
            ) from exc
        if response.status_code == 404:
            raise ApiError(
                f"Hangar has no data for {path}.",
                hint="The project may have been removed or renamed.",
            )
        if response.status_code == 429:
            raise ApiError(
                "Hangar is rate limiting requests.",
                hint="Wait a minute and try again.",
            )
        if response.status_code >= 400:
            raise ApiError(f"Hangar returned HTTP {response.status_code} for {path}.")
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError("Hangar returned invalid JSON.") from exc

    # ---------------------------------------------------------------- search
    def search(
        self,
        query: str,
        *,
        platform: str,
        game_version: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ContentHit]:
        """Search plugins for a Hangar platform and Minecraft version."""
        params: dict[str, Any] = {
            "q": query,
            "limit": max(1, min(int(limit), 100)),
            "offset": max(0, int(offset)),
            "platform": platform.upper(),
        }
        if game_version:
            params["version"] = game_version
        data = self._get("projects", params)
        if not isinstance(data, dict):
            raise ApiError("Hangar returned an unexpected search payload.")
        hits: list[ContentHit] = []
        for item in data.get("result", []):
            if not isinstance(item, dict):
                continue
            if game_version and not _supports(
                item.get("supportedPlatforms"), platform, game_version
            ):
                continue
            hits.append(self._parse_hit(item, platform, game_version))
        return hits

    def project(self, slug: str, *, platform: str) -> ContentHit:
        data = self._get(f"projects/{quote(slug, safe='')}")
        if not isinstance(data, dict):
            raise ApiError(f"Hangar returned an unexpected project for {slug}.")
        return self._parse_hit(data, platform, None)

    # -------------------------------------------------------------- versions
    def versions(
        self,
        slug: str,
        *,
        platform: str,
        game_version: str | None = None,
        limit: int = 25,
    ) -> list[ContentVersion]:
        """Return compatible plugin versions, newest first."""
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 100)),
            "platform": platform.upper(),
        }
        if game_version:
            params["platformVersion"] = game_version
        data = self._get(f"projects/{quote(slug, safe='')}/versions", params)
        if not isinstance(data, dict):
            raise ApiError(
                f"Hangar returned an unexpected version list for {slug}."
            )
        versions: list[ContentVersion] = []
        for item in data.get("result", []):
            if not isinstance(item, dict):
                continue
            version = self._parse_version(item, slug, platform)
            if game_version and game_version not in version.game_versions:
                continue
            if not version.download_url:
                continue
            versions.append(version)
        return versions

    def latest_version(
        self,
        slug: str,
        *,
        platform: str,
        game_version: str | None = None,
    ) -> ContentVersion:
        versions = self.versions(
            slug, platform=platform, game_version=game_version
        )
        if not versions:
            raise ApiError(
                f"No compatible version of {slug} was found on Hangar.",
                hint="Try another project or check the server's Minecraft version.",
            )
        releases = [
            version for version in versions if version.channel == "release"
        ]
        return (releases or versions)[0]

    # ---------------------------------------------------------------- parsing
    @staticmethod
    def _parse_hit(
        item: dict[str, Any],
        platform: str,
        game_version: str | None,
    ) -> ContentHit:
        namespace = item.get("namespace") or {}
        owner = str(namespace.get("owner") or "")
        slug = str(namespace.get("slug") or item.get("name") or "")
        stats = item.get("stats")
        if not isinstance(stats, dict):
            stats = {}
        project_id = str(item.get("id") or slug)
        url = (
            f"https://hangar.papermc.io/{quote(owner)}/{quote(slug)}"
            if owner
            else ""
        )
        return ContentHit(
            source=ContentSource.HANGAR,
            project_id=project_id,
            slug=slug,
            name=str(item.get("name") or slug),
            description=str(item.get("description") or ""),
            author=owner,
            downloads=_as_int(stats.get("downloads")),
            kind=ContentKind.PLUGIN,
            url=url,
        )

    @staticmethod
    def _parse_version(
        item: dict[str, Any], slug: str, platform: str
    ) -> ContentVersion:
        platform = platform.upper()
        downloads = item.get("downloads")
        download: dict[str, Any] = {}
        if isinstance(downloads, dict):
            candidate = downloads.get(platform)
            if isinstance(candidate, dict):
                download = candidate
        file_info = download.get("fileInfo")
        if not isinstance(file_info, dict):
            file_info = {}
        direct_url = str(download.get("downloadUrl") or "")
        external_url = str(download.get("externalUrl") or "")
        download_url = direct_url or external_url

        platform_versions = item.get("platformDependencies")
        game_versions: tuple[str, ...] = ()
        if isinstance(platform_versions, dict):
            raw = platform_versions.get(platform)
            if isinstance(raw, list):
                game_versions = tuple(str(version) for version in raw)

        dependencies: list[ContentDependency] = []
        raw_dependencies = item.get("pluginDependencies")
        if isinstance(raw_dependencies, dict):
            for raw in raw_dependencies.get(platform) or []:
                if not isinstance(raw, dict):
                    continue
                dependency_id = raw.get("projectId")
                dependencies.append(
                    ContentDependency(
                        name=str(raw.get("name") or dependency_id or "unknown"),
                        project_id=str(dependency_id) if dependency_id else None,
                        source=ContentSource.HANGAR,
                        required=bool(raw.get("required", True)),
                    )
                )

        channel = item.get("channel")
        channel_name = "release"
        if isinstance(channel, dict) and channel.get("name"):
            channel_name = str(channel["name"]).lower()

        version_id = str(item.get("id") or item.get("name") or "")
        version_name = str(item.get("name") or version_id)
        filename = str(
            file_info.get("name") or f"{slug}-{version_name}.jar"
        )
        size = _as_int(file_info.get("sizeBytes")) or None
        sha256 = str(file_info.get("sha256Hash") or "") or None
        return ContentVersion(
            source=ContentSource.HANGAR,
            project_id=str(item.get("projectId") or slug),
            version_id=version_id,
            name=version_name,
            version_number=version_name,
            filename=filename,
            download_url=download_url,
            game_versions=game_versions,
            loaders=(platform.lower(),),
            sha512=None,
            sha256=sha256,
            size=size,
            channel=channel_name,
            dependencies=tuple(dependencies),
            requires_manual_download=bool(external_url and not direct_url),
        )
