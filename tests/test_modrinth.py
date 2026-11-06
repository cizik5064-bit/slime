from __future__ import annotations

import json

import httpx
import pytest
import respx

from slime.api.modrinth import ModrinthClient
from slime.errors import ApiError
from slime.models import ContentKind, ContentSource, ContentVersion

BASE = "https://modrinth.example/v2"


@pytest.fixture
def client() -> ModrinthClient:
    return ModrinthClient(BASE, user_agent="Slime/test", timeout=5)


def test_search_sends_loader_and_version_facets(client: ModrinthClient) -> None:
    payload = {
        "hits": [
            {
                "project_id": "abc",
                "slug": "example-plugin",
                "title": "Example Plugin",
                "description": "Does things",
                "author": "Someone",
                "downloads": 1234,
                "project_type": "plugin",
            }
        ]
    }
    with respx.mock:
        route = respx.get(f"{BASE}/search").mock(
            return_value=httpx.Response(200, json=payload)
        )
        hits = client.search(
            "example",
            kind=ContentKind.PLUGIN,
            loaders=("paper", "spigot"),
            game_version="1.21.4",
        )

    assert len(hits) == 1
    hit = hits[0]
    assert hit.source is ContentSource.MODRINTH
    assert hit.project_id == "abc"
    assert hit.slug == "example-plugin"
    assert hit.kind is ContentKind.PLUGIN
    assert hit.url == "https://modrinth.com/plugin/example-plugin"

    params = route.calls.last.request.url.params
    facets = json.loads(params["facets"])
    assert ["project_type:plugin"] in facets
    assert ["versions:1.21.4"] in facets
    assert ["categories:paper", "categories:spigot"] in facets


def test_versions_are_filtered_by_version_and_loader(
    client: ModrinthClient,
) -> None:
    payload = [
        {
            "id": "ver-new",
            "project_id": "abc",
            "name": "2.0",
            "version_number": "2.0",
            "version_type": "release",
            "game_versions": ["1.21.4"],
            "loaders": ["paper"],
            "files": [
                {
                    "primary": True,
                    "filename": "example-2.0.jar",
                    "url": "https://cdn.example/example-2.0.jar",
                    "size": 4096,
                    "hashes": {"sha512": "abc123", "sha256": "def456"},
                }
            ],
            "dependencies": [
                {
                    "project_id": "dep",
                    "version_id": None,
                    "dependency_type": "required",
                },
                {
                    "project_id": "optional",
                    "version_id": None,
                    "dependency_type": "optional",
                },
            ],
        },
        {
            "id": "ver-old",
            "project_id": "abc",
            "name": "1.0",
            "version_number": "1.0",
            "version_type": "release",
            "game_versions": ["1.20.6"],
            "loaders": ["paper"],
            "files": [
                {
                    "primary": True,
                    "filename": "example-1.0.jar",
                    "url": "https://cdn.example/example-1.0.jar",
                }
            ],
        },
    ]
    with respx.mock:
        respx.get(f"{BASE}/project/abc/version").mock(
            return_value=httpx.Response(200, json=payload)
        )
        versions = client.versions(
            "abc", kind=ContentKind.PLUGIN, loaders=("paper",), game_version="1.21.4"
        )

    assert [version.version_id for version in versions] == ["ver-new"]
    version = versions[0]
    assert version.filename == "example-2.0.jar"
    assert version.sha512 == "abc123"
    assert version.sha256 == "def456"
    assert version.size == 4096
    assert len(version.dependencies) == 2
    assert [dep.name for dep in version.required_dependencies] == ["dep"]
    assert version.required_dependencies[0].source is ContentSource.MODRINTH


def test_latest_version_prefers_release(client: ModrinthClient) -> None:
    payload = [
        {
            "id": "beta",
            "project_id": "abc",
            "name": "2.0-beta",
            "version_number": "2.0-beta",
            "version_type": "beta",
            "game_versions": ["1.21.4"],
            "loaders": ["paper"],
            "files": [
                {
                    "primary": True,
                    "filename": "beta.jar",
                    "url": "https://cdn.example/beta.jar",
                }
            ],
        },
        {
            "id": "release",
            "project_id": "abc",
            "name": "1.9",
            "version_number": "1.9",
            "version_type": "release",
            "game_versions": ["1.21.4"],
            "loaders": ["paper"],
            "files": [
                {
                    "primary": True,
                    "filename": "stable.jar",
                    "url": "https://cdn.example/stable.jar",
                }
            ],
        },
    ]
    with respx.mock:
        respx.get(f"{BASE}/project/abc/version").mock(
            return_value=httpx.Response(200, json=payload)
        )
        version = client.latest_version(
            "abc", kind=ContentKind.PLUGIN, loaders=("paper",), game_version="1.21.4"
        )

    assert isinstance(version, ContentVersion)
    assert version.version_id == "release"


def test_empty_compatible_versions_raise(client: ModrinthClient) -> None:
    payload = [
        {
            "id": "old",
            "project_id": "abc",
            "game_versions": ["1.20.6"],
            "loaders": ["paper"],
            "files": [{"url": "https://cdn.example/old.jar"}],
        }
    ]
    with respx.mock:
        respx.get(f"{BASE}/project/abc/version").mock(
            return_value=httpx.Response(200, json=payload)
        )
        with pytest.raises(ApiError, match="No compatible version"):
            client.latest_version(
                "abc", loaders=("paper",), game_version="1.21.4"
            )
