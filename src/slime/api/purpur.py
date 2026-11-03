"""Client for the Purpur API v2.

Purpur is a Paper fork with extra configuration options. Its download API is
separate from the PaperMC Fill API:
https://api.purpurmc.org/v2/purpur

The client exposes the same shape as :class:`slime.api.papermc.PaperMCClient`
so the rest of Slime can treat all projects uniformly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from .. import __version__
from ..errors import ApiError
from ..models import BuildInfo, DownloadInfo, sort_versions

DEFAULT_BASE_URL = "https://api.purpurmc.org/v2/purpur"


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class PurpurClient:
    """Thin synchronous client around the Purpur API v2."""

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

    def __enter__(self) -> PurpurClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _get(self, path: str = "") -> Any:
        url = self.base_url if not path else f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            raise ApiError(
                f"Could not reach the Purpur API: {exc}",
                hint="Check your internet connection or try again in a minute.",
            ) from exc
        if response.status_code == 404:
            raise ApiError(
                f"Purpur API has no data for {path or 'this project'}.",
                hint="The Minecraft version or build may not exist yet.",
            )
        if response.status_code >= 400:
            raise ApiError(f"Purpur API returned HTTP {response.status_code} for {path}.")
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError("Purpur API returned invalid JSON.") from exc

    # -------------------------------------------------------------- versions
    def versions(self, project: str = "purpur") -> list[str]:
        data = self._get()
        raw = data.get("versions", data) if isinstance(data, dict) else data
        if not isinstance(raw, list):
            raise ApiError("Purpur API returned an unexpected version list.")
        versions = [str(item).strip() for item in raw if str(item).strip()]
        if not versions:
            raise ApiError(f"Purpur API returned no versions for project '{project}'.")
        return sort_versions(versions)

    def latest_version(self, project: str = "purpur") -> str:
        versions = self.versions(project)
        if not versions:
            raise ApiError(f"No versions are available for project '{project}'.")
        return versions[0]

    # ---------------------------------------------------------------- builds
    def builds(self, project: str, version: str) -> list[BuildInfo]:
        data = self._get(quote(version, safe=""))
        raw = data.get("builds", data) if isinstance(data, dict) else data
        if isinstance(raw, dict):
            raw = raw.get("all", raw.get("builds"))
        if not isinstance(raw, list):
            raise ApiError(
                f"Unexpected build list for {project} {version}: expected a JSON array."
            )
        build_ids = sorted(
            {
                build_id
                for item in raw
                if (build_id := _as_int(item)) is not None
            }
        )
        if not build_ids:
            raise ApiError(
                f"No builds found for {project} {version}.",
                hint="Try another version: slime server versions --project " + project,
            )
        return [self._build_info(version, build_id) for build_id in build_ids]

    def build(self, project: str, version: str, build: int) -> BuildInfo:
        data = self._get(f"{quote(version, safe='')}/{int(build)}")
        if not isinstance(data, dict):
            raise ApiError(f"Unexpected response for {project} {version} build {build}.")
        return self._parse_build(version, build, data)

    def latest_build(
        self,
        project: str,
        version: str,
        *,
        channel: str = "STABLE",
    ) -> BuildInfo:
        # Purpur has a single build stream, so the channel selector does not
        # apply. The dedicated endpoint already resolves the latest build.
        data = self._get(f"{quote(version, safe='')}/latest")
        if not isinstance(data, dict):
            raise ApiError(f"Unexpected response for {project} {version} latest build.")
        build_id = _as_int(data.get("build"))
        if build_id is None:
            raise ApiError(f"Purpur API did not report a latest build for {version}.")
        return self._parse_build(version, build_id, data)

    def _build_info(
        self,
        version: str,
        build_id: int,
        *,
        time: str | None = None,
    ) -> BuildInfo:
        version_part = quote(version, safe="")
        download = DownloadInfo(
            name=f"purpur-{version}-{build_id}.jar",
            url=f"{self.base_url}/{version_part}/{build_id}/download",
        )
        return BuildInfo(
            project="purpur",
            version=version,
            build=build_id,
            channel="STABLE",
            time=time,
            downloads={"server:default": download},
        )

    def _parse_build(self, version: str, build_id: int, item: dict[str, Any]) -> BuildInfo:
        result = str(item.get("result") or "SUCCESS").upper()
        if result != "SUCCESS":
            raise ApiError(
                f"Purpur build {build_id} for {version} finished with status {result}.",
                hint="Choose another build: slime server builds " + version,
            )
        timestamp = _as_int(item.get("timestamp"))
        time = None
        if timestamp is not None:
            time = datetime.fromtimestamp(timestamp / 1000, UTC).isoformat(
                timespec="seconds"
            )
        return self._build_info(version, build_id, time=time)
