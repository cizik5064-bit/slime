"""Client for the Modrinth API v2.

Modrinth hosts plugins and mods for many loaders. Slime only asks for content
that matches the server's Minecraft version and loader, then re-checks the
response because Modrinth occasionally returns a superset of the facets.

Documentation: https://docs.modrinth.com/api/
"""

from __future__ import annotations

import json
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

DEFAULT_BASE_URL = "https://api.modrinth.com/v2"

_PROJECT_TYPE = {
    ContentKind.PLUGIN: "plugin",
    ContentKind.MOD: "mod",
}


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if item)


class ModrinthClient:
    """Thin synchronous client around the Modrinth API v2."""

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

    def __enter__(self) -> ModrinthClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ApiError(
                f"Could not reach Modrinth: {exc}",
                hint="Check your internet connection or try again in a minute.",
            ) from exc
        if response.status_code == 404:
            raise ApiError(
                f"Modrinth has no data for {path}.",
                hint="The project may have been removed or renamed.",
            )
        if response.status_code == 429:
            raise ApiError(
                "Modrinth is rate limiting requests.",
                hint="Wait a minute and try again.",
            )
        if response.status_code >= 400:
            raise ApiError(f"Modrinth returned HTTP {response.status_code} for {path}.")
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError("Modrinth returned invalid JSON.") from exc

    # ---------------------------------------------------------------- search
    def search(
        self,
        query: str,
        *,
        kind: ContentKind = ContentKind.PLUGIN,
        loaders: tuple[str, ...] | list[str] = (),
        game_version: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ContentHit]:
        """Search projects that match the loader and Minecraft version."""
        facets: list[list[str]] = [[f"project_type:{_PROJECT_TYPE[kind]}"]]
        if loaders:
            facets.append([f"categories:{loader}" for loader in loaders])
        if game_version:
            facets.append([f"versions:{game_version}"])
        params = {
            "query": query,
            "limit": max(1, min(int(limit), 100)),
            "offset": max(0, int(offset)),
            "facets": json.dumps(facets),
        }
        data = self._get("search", params)
        if not isinstance(data, dict):
            raise ApiError("Modrinth returned an unexpected search payload.")
        hits: list[ContentHit] = []
        for item in data.get("hits", []):
            if isinstance(item, dict):
                hits.append(self._parse_hit(item, kind))
        return hits

    def project(self, project_id: str, *, kind: ContentKind) -> ContentHit:
        data = self._get(f"project/{quote(project_id, safe='')}")
        if not isinstance(data, dict):
            raise ApiError(f"Modrinth returned an unexpected project for {project_id}.")
        return self._parse_hit(data, kind)

    # -------------------------------------------------------------- versions
    def versions(
        self,
        project_id: str,
        *,
        kind: ContentKind = ContentKind.PLUGIN,
        loaders: tuple[str, ...] | list[str] = (),
        game_version: str | None = None,
    ) -> list[ContentVersion]:
        """Return compatible versions, newest first."""
        data = self._get(f"project/{quote(project_id, safe='')}/version")
        if not isinstance(data, list):
            raise ApiError(
                f"Modrinth returned an unexpected version list for {project_id}."
            )
        versions: list[ContentVersion] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            version = self._parse_version(item, project_id, kind)
            if not self._matches(version, loaders, game_version):
                continue
            versions.append(version)
        versions.sort(key=lambda version: version.version_id, reverse=True)
        return versions

    def latest_version(
        self,
        project_id: str,
        *,
        kind: ContentKind = ContentKind.PLUGIN,
        loaders: tuple[str, ...] | list[str] = (),
        game_version: str | None = None,
    ) -> ContentVersion:
        versions = self.versions(
            project_id, kind=kind, loaders=loaders, game_version=game_version
        )
        if not versions:
            raise ApiError(
                f"No compatible version of {project_id} was found on Modrinth.",
                hint="Try another project or check the server's Minecraft version.",
            )
        releases = [version for version in versions if version.channel == "release"]
        return (releases or versions)[0]

    # ---------------------------------------------------------------- parsing
    @staticmethod
    def _parse_hit(item: dict[str, Any], default_kind: ContentKind) -> ContentHit:
        project_type = str(item.get("project_type") or "").lower()
        kind = ContentKind.MOD if project_type == "mod" else default_kind
        project_id = str(item.get("project_id") or item.get("id") or item.get("slug") or "")
        slug = str(item.get("slug") or project_id)
        return ContentHit(
            source=ContentSource.MODRINTH,
            project_id=project_id,
            slug=slug,
            name=str(item.get("title") or item.get("name") or slug),
            description=str(item.get("description") or ""),
            author=str(item.get("author") or ""),
            downloads=_as_int(item.get("downloads")),
            kind=kind,
            url=f"https://modrinth.com/{_PROJECT_TYPE[kind]}/{slug}",
        )

    @staticmethod
    def _parse_version(
        item: dict[str, Any], project_id: str, kind: ContentKind
    ) -> ContentVersion:
        files = item.get("files")
        chosen: dict[str, Any] = {}
        if isinstance(files, list):
            for candidate in files:
                if not isinstance(candidate, dict):
                    continue
                if candidate.get("primary") or not chosen:
                    chosen = candidate
                if candidate.get("primary"):
                    break
        hashes = chosen.get("hashes")
        if not isinstance(hashes, dict):
            hashes = {}
        dependencies: list[ContentDependency] = []
        for raw in item.get("dependencies") or []:
            if not isinstance(raw, dict):
                continue
            project = str(raw.get("project_id") or "")
            version_id = str(raw.get("version_id") or "")
            dependencies.append(
                ContentDependency(
                    name=project or version_id or "unknown",
                    project_id=project or None,
                    version_id=version_id or None,
                    source=ContentSource.MODRINTH,
                    required=str(raw.get("dependency_type") or "required") == "required",
                )
            )
        return ContentVersion(
            source=ContentSource.MODRINTH,
            project_id=str(item.get("project_id") or project_id),
            version_id=str(item.get("id") or ""),
            name=str(item.get("name") or item.get("version_number") or ""),
            version_number=str(item.get("version_number") or item.get("name") or ""),
            filename=str(
                chosen.get("filename") or f"{project_id}-{item.get('id') or 'latest'}.jar"
            ),
            download_url=str(chosen.get("url") or ""),
            game_versions=_strings(item.get("game_versions")),
            loaders=_strings(item.get("loaders")),
            sha512=str(hashes.get("sha512") or "") or None,
            sha256=str(hashes.get("sha256") or "") or None,
            size=_as_int(chosen.get("size")) or None,
            channel=str(item.get("version_type") or "release").lower(),
            dependencies=tuple(dependencies),
        )

    @staticmethod
    def _matches(
        version: ContentVersion,
        loaders: tuple[str, ...] | list[str],
        game_version: str | None,
    ) -> bool:
        if game_version and game_version not in version.game_versions:
            return False
        if loaders:
            wanted = {loader.lower() for loader in loaders}
            available = {loader.lower() for loader in version.loaders}
            if not wanted & available:
                return False
        return bool(version.download_url)
