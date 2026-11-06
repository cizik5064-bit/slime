from __future__ import annotations

from pathlib import Path

import pytest

from slime.config import Config
from slime.content import ContentManager
from slime.errors import ApiError, ContentError
from slime.models import (
    ContentDependency,
    ContentHit,
    ContentKind,
    ContentSource,
    ContentVersion,
    Server,
)
from slime.store import ServerStore


def make_server(**overrides: object) -> Server:
    values: dict[str, object] = {
        "name": "survival",
        "project": "paper",
        "minecraft_version": "1.21.4",
        "build": 1,
        "java_major": 21,
        "port": 25565,
    }
    values.update(overrides)
    return Server(**values)  # type: ignore[arg-type]


def make_version(
    project_id: str,
    *,
    name: str = "",
    version_id: str = "",
    filename: str = "",
    dependencies: tuple[ContentDependency, ...] = (),
    source: ContentSource = ContentSource.MODRINTH,
) -> ContentVersion:
    return ContentVersion(
        source=source,
        project_id=project_id,
        version_id=version_id or f"{project_id}-1",
        name=name or project_id,
        version_number=version_id or "1.0",
        filename=filename or f"{project_id}.jar",
        download_url=f"https://cdn.example/{filename or project_id + '.jar'}",
        game_versions=("1.21.4",),
        loaders=("paper",),
        dependencies=dependencies,
    )


class FakeModrinth:
    def __init__(
        self,
        versions: dict[str, ContentVersion],
        hits: list[ContentHit] | None = None,
    ) -> None:
        self.versions_by_project = versions
        self.hits = hits or []
        self.calls: list[str] = []

    def project(self, project_id: str, *, kind: ContentKind) -> ContentHit:
        for hit in self.hits:
            if project_id in {hit.slug, hit.project_id}:
                return hit
        raise ApiError("not found")

    def search(self, *args: object, **kwargs: object) -> list[ContentHit]:
        return list(self.hits)

    def versions(self, project_id: str, **kwargs: object) -> list[ContentVersion]:
        version = self.versions_by_project.get(project_id)
        return [version] if version else []

    def latest_version(
        self, project_id: str, **kwargs: object
    ) -> ContentVersion:
        self.calls.append(project_id)
        version = self.versions_by_project.get(project_id)
        if version is None:
            raise ApiError(f"missing {project_id}")
        return version

    def close(self) -> None:
        pass


class FakeHangar:
    def __init__(self) -> None:
        self.hits: list[ContentHit] = []
        self.versions_by_slug: dict[str, ContentVersion] = {}

    def project(self, slug: str, *, platform: str) -> ContentHit:
        raise ApiError("not found")

    def search(self, *args: object, **kwargs: object) -> list[ContentHit]:
        return list(self.hits)

    def versions(self, slug: str, **kwargs: object) -> list[ContentVersion]:
        version = self.versions_by_slug.get(slug)
        return [version] if version else []

    def latest_version(self, slug: str, **kwargs: object) -> ContentVersion:
        version = self.versions_by_slug.get(slug)
        if version is None:
            raise ApiError(f"missing {slug}")
        return version

    def close(self) -> None:
        pass


@pytest.fixture
def server(config: Config) -> Server:
    store = ServerStore(config)
    value = make_server()
    store.save(value)
    return value


@pytest.fixture
def fake_download(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    written: list[Path] = []

    def download(url: str, destination: Path, **kwargs: object) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"jar-bytes")
        written.append(destination)
        return destination

    monkeypatch.setattr("slime.content.download_file", download)
    return written


def make_manager(
    config: Config,
    *,
    modrinth: FakeModrinth | None = None,
    hangar: FakeHangar | None = None,
) -> ContentManager:
    return ContentManager(
        config,
        ServerStore(config),
        modrinth=modrinth or FakeModrinth({}),
        hangar=hangar or FakeHangar(),
    )


def test_install_resolves_required_dependencies(
    config: Config, server: Server, fake_download: list[Path]
) -> None:
    dependency = ContentDependency(
        name="dep",
        project_id="dep",
        source=ContentSource.MODRINTH,
        required=True,
    )
    modrinth = FakeModrinth(
        {
            "main": make_version("main", dependencies=(dependency,)),
            "dep": make_version("dep"),
        }
    )
    manager = make_manager(config, modrinth=modrinth)

    result = manager.install(server, modrinth.versions_by_project["main"])

    assert [item.filename for item in result.installed] == ["main.jar", "dep.jar"]
    plugins = Path(config.paths.servers) / "survival" / "plugins"
    assert sorted(path.name for path in plugins.glob("*.jar")) == [
        "dep.jar",
        "main.jar",
    ]
    manifest = manager.manifest_path(server).read_text(encoding="utf-8")
    assert '"project_id": "main"' in manifest
    assert '"project_id": "dep"' in manifest


def test_install_skips_duplicate_project(
    config: Config, server: Server, fake_download: list[Path]
) -> None:
    version = make_version("main")
    modrinth = FakeModrinth({"main": version})
    manager = make_manager(config, modrinth=modrinth)

    first = manager.install(server, version)
    second = manager.install(server, version)

    assert first.count == 1
    assert second.count == 0
    assert "already installed" in second.skipped[0]
    plugins = Path(config.paths.servers) / "survival" / "plugins"
    assert len(list(plugins.glob("*.jar"))) == 1


def test_filename_collision_requires_overwrite(
    config: Config, server: Server, fake_download: list[Path]
) -> None:
    first = make_version("one", filename="same.jar", version_id="1")
    second = make_version("two", filename="same.jar", version_id="2")
    manager = make_manager(config)

    manager.install(server, first)
    skipped = manager.install(server, second)
    assert skipped.count == 0
    assert "use --overwrite" in skipped.skipped[0]

    replaced = manager.install(server, second, overwrite=True)
    assert replaced.count == 1
    assert replaced.installed[0].project_id == "two"


def test_install_rejects_mods_for_plugin_only_project(
    config: Config, server: Server, fake_download: list[Path]
) -> None:
    manager = make_manager(config)
    version = make_version("main")
    with pytest.raises(ContentError, match="does not support mods"):
        manager.install(server, version, kind=ContentKind.MOD)


def test_manual_download_is_rejected(
    config: Config, server: Server, fake_download: list[Path]
) -> None:
    version = make_version("main")
    version.requires_manual_download = True
    manager = make_manager(config)
    with pytest.raises(ContentError, match="external download"):
        manager.install(server, version)


def test_install_without_dependencies(
    config: Config, server: Server, fake_download: list[Path]
) -> None:
    dependency = ContentDependency(
        name="dep", project_id="dep", source=ContentSource.MODRINTH
    )
    modrinth = FakeModrinth(
        {
            "main": make_version("main", dependencies=(dependency,)),
            "dep": make_version("dep"),
        }
    )
    manager = make_manager(config, modrinth=modrinth)

    result = manager.install(
        server, modrinth.versions_by_project["main"], with_dependencies=False
    )

    assert [item.project_id for item in result.installed] == ["main"]


def test_missing_dependency_is_a_warning(
    config: Config, server: Server, fake_download: list[Path]
) -> None:
    dependency = ContentDependency(
        name="missing", project_id="missing", source=ContentSource.MODRINTH
    )
    modrinth = FakeModrinth({"main": make_version("main", dependencies=(dependency,))})
    manager = make_manager(config, modrinth=modrinth)

    result = manager.install(server, modrinth.versions_by_project["main"])

    assert result.count == 1
    assert "missing" in result.warnings[0]


def test_install_cycle_does_not_recurse_forever(
    config: Config, server: Server, fake_download: list[Path]
) -> None:
    first_dep = ContentDependency(
        name="two", project_id="two", source=ContentSource.MODRINTH
    )
    second_dep = ContentDependency(
        name="one", project_id="one", source=ContentSource.MODRINTH
    )
    modrinth = FakeModrinth(
        {
            "one": make_version("one", dependencies=(first_dep,)),
            "two": make_version("two", dependencies=(second_dep,)),
        }
    )
    manager = make_manager(config, modrinth=modrinth)

    result = manager.install(server, modrinth.versions_by_project["one"])

    assert [item.project_id for item in result.installed] == ["one", "two"]


def test_installed_and_remove(
    config: Config, server: Server, fake_download: list[Path]
) -> None:
    version = make_version("main", name="Main Plugin")
    manager = make_manager(config)
    manager.install(server, version)

    installed = manager.installed(server)
    assert len(installed) == 1
    assert installed[0].filename == "main.jar"
    assert installed[0].name == "Main Plugin"
    assert installed[0].source is ContentSource.MODRINTH

    removed = manager.remove(server, "main")
    assert removed.filename == "main.jar"
    assert manager.installed(server) == []


def test_remove_unknown_content_raises(
    config: Config, server: Server, fake_download: list[Path]
) -> None:
    manager = make_manager(config)
    with pytest.raises(ContentError, match="not installed"):
        manager.remove(server, "nope")


def test_search_combines_sources_and_filters(
    config: Config, server: Server
) -> None:
    modrinth_hit = ContentHit(
        source=ContentSource.MODRINTH,
        project_id="a",
        slug="a",
        name="A",
        description="",
        author="",
        downloads=10,
        kind=ContentKind.PLUGIN,
    )
    hangar_hit = ContentHit(
        source=ContentSource.HANGAR,
        project_id="2",
        slug="B",
        name="B",
        description="",
        author="",
        downloads=20,
        kind=ContentKind.PLUGIN,
    )
    hangar = FakeHangar()
    hangar.hits = [hangar_hit]
    manager = make_manager(
        config,
        modrinth=FakeModrinth({}, hits=[modrinth_hit]),
        hangar=hangar,
    )

    hits = manager.search(server, "anything")

    assert [hit.name for hit in hits] == ["B", "A"]
