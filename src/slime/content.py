"""Plugin and mod discovery, installation and duplicate checks.

The module glues the Modrinth and Hangar clients to a server: it filters
results by the server's Minecraft version and loader, installs jars into the
correct ``plugins/`` or ``mods/`` folder, resolves required dependencies
recursively, and records what was installed in ``slime-content.json``.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .api.hangar import HangarClient
from .api.modrinth import ModrinthClient
from .config import Config
from .errors import ApiError, ContentError, DownloadError
from .models import (
    ContentHit,
    ContentKind,
    ContentSource,
    ContentVersion,
    InstalledContent,
    Server,
)
from .store import ServerStore
from .utils.downloads import download_file

MANIFEST_FILE = "slime-content.json"
FORMAT_VERSION = 1

DownloadProgress = Callable[[int, int | None], None]


def _sha512(path: Path) -> str:
    digest = hashlib.sha512()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_filename(filename: str) -> str:
    name = filename.replace("\\", "/").split("/")[-1].strip()
    if not name or name in {".", ".."}:
        raise ContentError("The content file has no usable file name.")
    return name


@dataclass(slots=True)
class InstallResult:
    """Outcome of installing one project and its required dependencies."""

    installed: list[InstalledContent] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.installed)


class ContentManager:
    """Search, install, list and remove plugins/mods for a server."""

    def __init__(
        self,
        config: Config,
        store: ServerStore,
        *,
        modrinth: ModrinthClient | None = None,
        hangar: HangarClient | None = None,
    ) -> None:
        settings = config.settings
        self.config = config
        self.store = store
        self.modrinth = modrinth or ModrinthClient(
            settings.modrinth_base_url,
            user_agent=settings.user_agent,
            timeout=settings.request_timeout,
        )
        self.hangar = hangar or HangarClient(
            settings.hangar_base_url,
            user_agent=settings.user_agent,
            timeout=settings.request_timeout,
        )
        self._owns_modrinth = modrinth is None
        self._owns_hangar = hangar is None

    def close(self) -> None:
        if self._owns_modrinth:
            self.modrinth.close()
        if self._owns_hangar:
            self.hangar.close()

    def __enter__(self) -> ContentManager:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------ paths
    def server_directory(self, server: Server) -> Path:
        return self.store.path(server.name)

    def default_kind(self, server: Server) -> ContentKind:
        if server.project.supports_plugins:
            return ContentKind.PLUGIN
        if server.project.supports_mods:
            return ContentKind.MOD
        raise ContentError(
            f"{server.project.display_name} does not load plugins or mods.",
        )

    def target_directory(
        self, server: Server, kind: ContentKind | None = None
    ) -> Path:
        kind = kind or self.default_kind(server)
        if kind.directory not in server.project.content_directories:
            raise ContentError(
                f"{server.project.display_name} does not support {kind.value}s.",
                hint=f"Supported folders: {', '.join(server.project.content_directories) or 'none'}.",
            )
        return self.server_directory(server) / kind.directory

    def manifest_path(self, server: Server) -> Path:
        return self.server_directory(server) / MANIFEST_FILE

    # ----------------------------------------------------------------- search
    def search(
        self,
        server: Server,
        query: str,
        *,
        kind: ContentKind | None = None,
        source: ContentSource | None = None,
        limit: int = 20,
    ) -> list[ContentHit]:
        """Search every enabled source for compatible content."""
        kind = kind or self.default_kind(server)
        if kind.directory not in server.project.content_directories:
            raise ContentError(
                f"{server.project.display_name} does not support {kind.value}s."
            )
        hits: list[ContentHit] = []
        if source in (None, ContentSource.MODRINTH):
            hits.extend(
                self.modrinth.search(
                    query,
                    kind=kind,
                    loaders=server.project.modrinth_loaders,
                    game_version=server.minecraft_version,
                    limit=limit,
                )
            )
        if source in (None, ContentSource.HANGAR) and kind is ContentKind.PLUGIN:
            try:
                hits.extend(
                    self.hangar.search(
                        query,
                        platform=server.project.hangar_platform,
                        game_version=server.minecraft_version,
                        limit=limit,
                    )
                )
            except ApiError:
                if source is ContentSource.HANGAR:
                    raise
        hits.sort(key=lambda hit: hit.downloads, reverse=True)
        return hits

    def versions(
        self,
        server: Server,
        hit: ContentHit,
        *,
        kind: ContentKind | None = None,
    ) -> list[ContentVersion]:
        kind = kind or hit.kind
        if hit.source is ContentSource.MODRINTH:
            return self.modrinth.versions(
                hit.project_id,
                kind=kind,
                loaders=server.project.modrinth_loaders,
                game_version=server.minecraft_version,
            )
        return self.hangar.versions(
            hit.slug,
            platform=server.project.hangar_platform,
            game_version=server.minecraft_version,
        )

    def latest_version(
        self,
        server: Server,
        hit: ContentHit,
        *,
        kind: ContentKind | None = None,
    ) -> ContentVersion:
        kind = kind or hit.kind
        if hit.source is ContentSource.MODRINTH:
            return self.modrinth.latest_version(
                hit.project_id,
                kind=kind,
                loaders=server.project.modrinth_loaders,
                game_version=server.minecraft_version,
            )
        return self.hangar.latest_version(
            hit.slug,
            platform=server.project.hangar_platform,
            game_version=server.minecraft_version,
        )

    def find(
        self,
        server: Server,
        query: str,
        *,
        source: ContentSource | None = None,
        kind: ContentKind | None = None,
    ) -> ContentHit:
        """Resolve a project id, slug or search phrase to a single hit."""
        needle = query.strip()
        if not needle:
            raise ContentError("A project name, slug or id is required.")
        kind = kind or self.default_kind(server)
        if source in (None, ContentSource.MODRINTH):
            try:
                return self.modrinth.project(needle, kind=kind)
            except ApiError:
                pass
        if source in (None, ContentSource.HANGAR) and kind is ContentKind.PLUGIN:
            try:
                return self.hangar.project(
                    needle, platform=server.project.hangar_platform
                )
            except ApiError:
                pass
        hits = self.search(server, needle, source=source, kind=kind, limit=10)
        if not hits:
            raise ContentError(
                f"No compatible content found for '{query}'.",
                hint="Check the spelling or try a different search term.",
            )
        lowered = needle.lower()
        exact = [
            hit
            for hit in hits
            if lowered in {hit.slug.lower(), hit.project_id.lower(), hit.name.lower()}
        ]
        return (exact or hits)[0]

    # ---------------------------------------------------------------- install
    def install(
        self,
        server: Server,
        version: ContentVersion,
        *,
        kind: ContentKind | None = None,
        with_dependencies: bool = True,
        overwrite: bool = False,
        progress: DownloadProgress | None = None,
    ) -> InstallResult:
        """Install ``version`` plus required dependencies into the server."""
        kind = kind or self.default_kind(server)
        target = self.target_directory(server, kind)
        result = InstallResult()
        self._install_one(
            server,
            version,
            kind,
            target,
            result,
            overwrite=overwrite,
            with_dependencies=with_dependencies,
            progress=progress,
            visited=set(),
        )
        return result

    def _install_one(
        self,
        server: Server,
        version: ContentVersion,
        kind: ContentKind,
        target: Path,
        result: InstallResult,
        *,
        overwrite: bool,
        with_dependencies: bool,
        progress: DownloadProgress | None,
        visited: set[str],
    ) -> None:
        identity = self._version_identity(version)
        if identity in visited:
            return
        visited.add(identity)

        duplicate = self._find_duplicate(server, version, kind)
        if duplicate is not None:
            if duplicate.version_id == version.version_id:
                result.skipped.append(f"{version.name} is already installed")
                return
            if not overwrite:
                result.skipped.append(
                    f"{version.name} is already installed "
                    f"({duplicate.filename}); use --overwrite to replace it"
                )
                return

        if version.requires_manual_download:
            raise ContentError(
                f"{version.name} only offers an external download.",
                hint=(
                    "Download it manually from the project page and place the jar "
                    f"in {target}."
                ),
            )

        target.mkdir(parents=True, exist_ok=True)
        destination = target / _safe_filename(version.filename)
        cached = self.config.paths.cache / "content" / _safe_filename(
            version.filename
        )
        try:
            download_file(
                version.download_url,
                cached,
                sha256=version.sha256,
                size=version.size,
                user_agent=self.config.settings.user_agent,
                timeout=self.config.settings.request_timeout,
                progress=progress,
            )
            if version.sha512:
                actual = _sha512(cached)
                if actual.lower() != version.sha512.lower():
                    raise DownloadError(
                        f"Checksum mismatch for {version.filename}.",
                        hint=f"Expected {version.sha512}, got {actual}.",
                    )
            os.replace(cached, destination)
        except (OSError, DownloadError) as exc:
            raise ContentError(
                f"Could not install {version.name}: {exc}",
                hint="Check your internet connection, disk space and permissions.",
            ) from exc

        installed = InstalledContent(
            path=str(destination),
            filename=destination.name,
            kind=kind,
            size=destination.stat().st_size,
            sha512=version.sha512 or _sha512(destination),
            source=version.source,
            project_id=version.project_id,
            version_id=version.version_id,
            name=version.name,
        )
        self._record(server, installed)
        result.installed.append(installed)

        if not with_dependencies:
            return
        for dependency in version.required_dependencies:
            resolved = self._resolve_dependency(server, dependency, kind)
            if resolved is None:
                result.warnings.append(
                    f"Required dependency '{dependency.name}' was not found"
                )
                continue
            self._install_one(
                server,
                resolved,
                kind,
                target,
                result,
                overwrite=overwrite,
                with_dependencies=True,
                progress=progress,
                visited=visited,
            )

    def _resolve_dependency(
        self,
        server: Server,
        dependency: Any,
        kind: ContentKind,
    ) -> ContentVersion | None:
        source = dependency.source or ContentSource.MODRINTH
        try:
            if source is ContentSource.MODRINTH and dependency.project_id:
                return self.modrinth.latest_version(
                    dependency.project_id,
                    kind=kind,
                    loaders=server.project.modrinth_loaders,
                    game_version=server.minecraft_version,
                )
            if source is ContentSource.HANGAR:
                return self._resolve_hangar_dependency(server, dependency)
        except ApiError:
            pass
        if dependency.project_id:
            try:
                return self.modrinth.latest_version(
                    dependency.project_id,
                    kind=kind,
                    loaders=server.project.modrinth_loaders,
                    game_version=server.minecraft_version,
                )
            except ApiError:
                return None
        return None

    def _resolve_hangar_dependency(
        self, server: Server, dependency: Any
    ) -> ContentVersion | None:
        if dependency.project_id:
            try:
                return self.hangar.latest_version(
                    dependency.project_id,
                    platform=server.project.hangar_platform,
                    game_version=server.minecraft_version,
                )
            except ApiError:
                pass
        hits = self.hangar.search(
            dependency.name,
            platform=server.project.hangar_platform,
            game_version=server.minecraft_version,
            limit=10,
        )
        lowered = dependency.name.lower()
        for hit in hits:
            if hit.slug.lower() == lowered or hit.name.lower() == lowered:
                return self.hangar.latest_version(
                    hit.slug,
                    platform=server.project.hangar_platform,
                    game_version=server.minecraft_version,
                )
        return None

    # ---------------------------------------------------------------- listing
    def installed(
        self,
        server: Server,
        *,
        kind: ContentKind | None = None,
    ) -> list[InstalledContent]:
        kinds = [kind] if kind is not None else [
            ContentKind(directory[:-1])
            for directory in server.project.content_directories
            if directory in {"plugins", "mods"}
        ]
        entries = self._read_manifest(server)
        result: list[InstalledContent] = []
        for content_kind in kinds:
            directory = self.server_directory(server) / content_kind.directory
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.jar")):
                key = f"{content_kind.directory}/{path.name}"
                record = entries.get(key, {})
                result.append(
                    InstalledContent(
                        path=str(path),
                        filename=path.name,
                        kind=content_kind,
                        size=path.stat().st_size,
                        sha512=str(record.get("sha512") or ""),
                        source=(
                            ContentSource(str(record["source"]))
                            if record.get("source")
                            else None
                        ),
                        project_id=str(record.get("project_id") or ""),
                        version_id=str(record.get("version_id") or ""),
                        name=str(record.get("name") or path.stem),
                    )
                )
        return result

    def remove(
        self,
        server: Server,
        identifier: str,
        *,
        kind: ContentKind | None = None,
    ) -> InstalledContent:
        wanted = identifier.strip().lower()
        if not wanted:
            raise ContentError("A file name or project id is required.")
        for content in self.installed(server, kind=kind):
            match = {
                content.filename.lower(),
                Path(content.filename).stem.lower(),
                content.project_id.lower(),
                content.name.lower(),
            }
            if wanted in match:
                try:
                    Path(content.path).unlink()
                except OSError as exc:
                    raise ContentError(
                        f"Could not remove {content.filename}: {exc}"
                    ) from exc
                self._forget(server, content)
                return content
        raise ContentError(
            f"'{identifier}' is not installed on this server.",
            hint="Run `slime content list NAME` to see installed files.",
        )

    # -------------------------------------------------------------- duplicate
    def _find_duplicate(
        self, server: Server, version: ContentVersion, kind: ContentKind
    ) -> InstalledContent | None:
        filename = _safe_filename(version.filename)
        for content in self.installed(server, kind=kind):
            if (
                content.project_id
                and version.project_id
                and content.project_id == version.project_id
                and content.source is version.source
            ):
                return content
            if content.filename.lower() == filename.lower():
                return content
            if (
                version.sha512
                and content.sha512
                and content.sha512.lower() == version.sha512.lower()
            ):
                return content
        return None

    def _version_identity(self, version: ContentVersion) -> str:
        if version.project_id:
            return f"{version.source.value}:{version.project_id}"
        return f"{version.source.value}:{version.filename}".lower()

    # --------------------------------------------------------------- manifest
    def _read_manifest(self, server: Server) -> dict[str, dict[str, Any]]:
        path = self.manifest_path(server)
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            return {}
        return {
            str(key): value
            for key, value in entries.items()
            if isinstance(value, dict)
        }

    def _write_manifest(
        self, server: Server, entries: dict[str, dict[str, Any]]
    ) -> None:
        path = self.manifest_path(server)
        payload = {"format": FORMAT_VERSION, "entries": entries}
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _record(self, server: Server, content: InstalledContent) -> None:
        entries = self._read_manifest(server)
        key = f"{content.kind.directory}/{content.filename}"
        entries[key] = {
            "source": content.source.value if content.source else "",
            "project_id": content.project_id,
            "version_id": content.version_id,
            "name": content.name,
            "sha512": content.sha512,
        }
        self._write_manifest(server, entries)

    def _forget(self, server: Server, content: InstalledContent) -> None:
        entries = self._read_manifest(server)
        key = f"{content.kind.directory}/{content.filename}"
        if entries.pop(key, None) is not None:
            self._write_manifest(server, entries)
