"""Client for the PaperMC Fill API v3.

Fill is the official download API for Paper, Folia, Velocity and Waterfall.
Documentation: https://docs.papermc.io/misc/download-api/

The parser is deliberately tolerant: Fill has changed small details between
v2 and v3, and self-hosted mirrors may wrap payloads slightly differently.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from ..errors import ApiError
from ..models import BuildInfo, DownloadInfo, sort_versions

DEFAULT_BASE_URL = "https://fill.papermc.io/v3"


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _project_id(value: Any) -> str | None:
    """Extract a project id from a Fill project object or plain string."""
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        nested = value.get("project")
        if isinstance(nested, dict):
            value = nested
        project_id = value.get("id") or value.get("project")
        return str(project_id) if project_id else None
    return None


def _version_id(value: Any) -> str | None:
    """Extract a Minecraft version id from any Fill v3 version shape."""
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        nested = value.get("version")
        if isinstance(nested, dict):
            value = nested
        elif isinstance(nested, str):
            return nested or None
        version_id = value.get("id") or value.get("version")
        return str(version_id) if version_id else None
    return None


class PaperMCClient:
    """Thin synchronous client around the Fill API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        user_agent: str = "Slime/0.1.0",
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

    def __enter__(self) -> PaperMCClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ApiError(
                f"Could not reach the PaperMC API: {exc}",
                hint="Check your internet connection or try again in a minute.",
            ) from exc
        if response.status_code == 404:
            raise ApiError(
                f"PaperMC API has no data for {path}.",
                hint="The project or Minecraft version may not exist yet.",
            )
        if response.status_code == 403:
            raise ApiError(
                "PaperMC API rejected the request (HTTP 403).",
                hint="Fill requires a descriptive User-Agent; update Slime or set one in config.toml.",
            )
        if response.status_code >= 400:
            raise ApiError(f"PaperMC API returned HTTP {response.status_code} for {path}.")
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError("PaperMC API returned invalid JSON.") from exc

    # -------------------------------------------------------------- projects
    def projects(self) -> dict[str, str]:
        data = self._get("projects")
        raw = data.get("projects", data) if isinstance(data, dict) else data
        result: dict[str, str] = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(value, dict):
                    nested = value.get("project")
                    if isinstance(nested, dict):
                        value = nested
                    project_id = str(value.get("id") or key)
                    result[project_id] = str(value.get("name") or project_id)
                else:
                    result[str(key)] = str(value)
        elif isinstance(raw, list):
            for item in raw:
                item_project_id = _project_id(item)
                if not item_project_id:
                    continue
                name = item_project_id
                if isinstance(item, dict):
                    nested = item.get("project")
                    project = nested if isinstance(nested, dict) else item
                    name = str(project.get("name") or item_project_id)
                result[item_project_id] = name
        if not result:
            raise ApiError("PaperMC API returned an empty project list.")
        return result

    # -------------------------------------------------------------- versions
    def version_groups(self, project: str) -> dict[str, list[str]]:
        data = self._get(f"projects/{quote(project, safe='')}/versions")
        raw = data.get("versions", data) if isinstance(data, dict) else data
        groups: dict[str, list[str]] = {}
        if isinstance(raw, dict):
            for group, versions in raw.items():
                if isinstance(versions, list):
                    parsed = [version for version in map(_version_id, versions) if version]
                    if parsed:
                        groups[str(group)] = parsed
        elif isinstance(raw, list):
            for item in raw:
                version = _version_id(item)
                if version:
                    groups.setdefault("all", []).append(version)
        if not groups:
            raise ApiError(f"PaperMC API returned no versions for project '{project}'.")
        return groups

    def versions(self, project: str) -> list[str]:
        groups = self.version_groups(project)
        flattened = {version for versions in groups.values() for version in versions}
        return sort_versions(list(flattened))

    def latest_version(self, project: str) -> str:
        versions = self.versions(project)
        if not versions:
            raise ApiError(f"No versions are available for project '{project}'.")
        return versions[0]

    # ---------------------------------------------------------------- builds
    def builds(self, project: str, version: str) -> list[BuildInfo]:
        project_part = quote(project, safe="")
        version_part = quote(version, safe="")
        data = self._get(f"projects/{project_part}/versions/{version_part}/builds")
        raw = data.get("builds", data) if isinstance(data, dict) else data
        if not isinstance(raw, list):
            raise ApiError(
                f"Unexpected build list for {project} {version}: expected a JSON array."
            )
        builds: list[BuildInfo] = []
        for item in raw:
            if isinstance(item, dict):
                builds.append(self._parse_build(project, version, item))
        if not builds:
            raise ApiError(
                f"No builds found for {project} {version}.",
                hint="Try another version: slime server versions --project " + project,
            )
        builds.sort(key=lambda build: build.build)
        return builds

    def build(self, project: str, version: str, build: int) -> BuildInfo:
        project_part = quote(project, safe="")
        version_part = quote(version, safe="")
        data = self._get(
            f"projects/{project_part}/versions/{version_part}/builds/{int(build)}"
        )
        raw = data.get("build", data) if isinstance(data, dict) else data
        if not isinstance(raw, dict):
            raise ApiError(f"Unexpected response for {project} {version} build {build}.")
        return self._parse_build(project, version, raw)

    def latest_build(
        self,
        project: str,
        version: str,
        *,
        channel: str = "STABLE",
    ) -> BuildInfo:
        builds = self.builds(project, version)
        requested = channel.strip().upper()
        if requested and requested != "ANY":
            matching = [build for build in builds if build.channel.upper() == requested]
            if matching:
                return max(matching, key=lambda build: build.build)
        return max(builds, key=lambda build: build.build)

    @staticmethod
    def _parse_build(project: str, version: str, item: dict[str, Any]) -> BuildInfo:
        build_id = _as_int(item.get("id", item.get("build")))
        if build_id is None:
            raise ApiError(f"Build for {project} {version} is missing an id.")

        downloads: dict[str, DownloadInfo] = {}
        raw_downloads = item.get("downloads") or {}
        if isinstance(raw_downloads, dict):
            for key, payload in raw_downloads.items():
                if not isinstance(payload, dict) or not payload.get("url"):
                    continue
                checksums = payload.get("checksums") or {}
                sha256 = checksums.get("sha256") if isinstance(checksums, dict) else None
                downloads[str(key)] = DownloadInfo(
                    name=str(
                        payload.get("name")
                        or f"{project}-{version}-{build_id}.jar"
                    ),
                    url=str(payload["url"]),
                    sha256=str(sha256) if sha256 else None,
                    size=_as_int(payload.get("size")),
                )

        return BuildInfo(
            project=str(item.get("project") or project),
            version=str(item.get("version") or version),
            build=build_id,
            channel=str(item.get("channel") or "STABLE").upper(),
            time=str(item["time"]) if item.get("time") else None,
            downloads=downloads,
        )
