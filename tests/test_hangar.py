from __future__ import annotations

import httpx
import pytest
import respx

from slime.api.hangar import HangarClient
from slime.errors import ApiError
from slime.models import ContentSource

BASE = "https://hangar.example/v1"


@pytest.fixture
def client() -> HangarClient:
    return HangarClient(BASE, user_agent="Slime/test", timeout=5)


def test_search_sends_platform_and_version(client: HangarClient) -> None:
    payload = {
        "pagination": {"count": 1, "limit": 20, "offset": 0},
        "result": [
            {
                "id": 23,
                "name": "Essentials",
                "namespace": {"owner": "EssentialsX", "slug": "Essentials"},
                "description": "The essential plugin suite",
                "stats": {"downloads": 1000},
            }
        ],
    }
    with respx.mock:
        route = respx.get(f"{BASE}/projects").mock(
            return_value=httpx.Response(200, json=payload)
        )
        hits = client.search("essentials", platform="PAPER", game_version="1.21.4")

    assert len(hits) == 1
    hit = hits[0]
    assert hit.source is ContentSource.HANGAR
    assert hit.project_id == "23"
    assert hit.slug == "Essentials"
    assert hit.author == "EssentialsX"
    assert hit.downloads == 1000
    assert hit.url == "https://hangar.papermc.io/EssentialsX/Essentials"

    params = route.calls.last.request.url.params
    assert params["platform"] == "PAPER"
    assert params["version"] == "1.21.4"


def test_search_drops_incompatible_supported_platforms(
    client: HangarClient,
) -> None:
    payload = {
        "pagination": {"count": 1, "limit": 20, "offset": 0},
        "result": [
            {
                "id": 5,
                "name": "Old Plugin",
                "namespace": {"owner": "Owner", "slug": "Old"},
                "supportedPlatforms": {"PAPER": ["1.20.6"]},
            }
        ],
    }
    with respx.mock:
        respx.get(f"{BASE}/projects").mock(
            return_value=httpx.Response(200, json=payload)
        )
        hits = client.search("old", platform="PAPER", game_version="1.21.4")

    assert hits == []


def test_versions_parse_downloads_and_dependencies(client: HangarClient) -> None:
    payload = {
        "pagination": {"count": 1, "limit": 25, "offset": 0},
        "result": [
            {
                "id": 13751,
                "projectId": 23,
                "name": "2.21.0",
                "channel": {"name": "Release"},
                "downloads": {
                    "PAPER": {
                        "downloadUrl": "https://cdn.example/essentials.jar",
                        "externalUrl": None,
                        "fileInfo": {
                            "name": "EssentialsX-2.21.0.jar",
                            "sizeBytes": 2048,
                            "sha256Hash": "deadbeef",
                        },
                    }
                },
                "pluginDependencies": {
                    "PAPER": [
                        {
                            "name": "Vault",
                            "projectId": None,
                            "required": True,
                            "externalUrl": None,
                            "platform": "PAPER",
                        }
                    ]
                },
                "platformDependencies": {
                    "PAPER": ["1.21.4", "1.21.5"]
                },
            }
        ],
    }
    with respx.mock:
        respx.get(f"{BASE}/projects/Essentials/versions").mock(
            return_value=httpx.Response(200, json=payload)
        )
        versions = client.versions(
            "Essentials", platform="PAPER", game_version="1.21.4"
        )

    assert len(versions) == 1
    version = versions[0]
    assert version.source is ContentSource.HANGAR
    assert version.filename == "EssentialsX-2.21.0.jar"
    assert version.download_url == "https://cdn.example/essentials.jar"
    assert version.sha256 == "deadbeef"
    assert version.channel == "release"
    assert version.game_versions == ("1.21.4", "1.21.5")
    assert [dep.name for dep in version.dependencies] == ["Vault"]


def test_external_only_download_is_flagged(client: HangarClient) -> None:
    payload = {
        "pagination": {"count": 1, "limit": 25, "offset": 0},
        "result": [
            {
                "id": 1,
                "name": "1.0",
                "downloads": {
                    "PAPER": {
                        "downloadUrl": None,
                        "externalUrl": "https://github.com/example/releases/1.0",
                        "fileInfo": None,
                    }
                },
                "platformDependencies": {"PAPER": ["1.21.4"]},
            }
        ],
    }
    with respx.mock:
        respx.get(f"{BASE}/projects/example/versions").mock(
            return_value=httpx.Response(200, json=payload)
        )
        versions = client.versions(
            "example", platform="PAPER", game_version="1.21.4"
        )

    assert versions[0].requires_manual_download is True


def test_incompatible_version_is_dropped(client: HangarClient) -> None:
    payload = {
        "pagination": {"count": 1, "limit": 25, "offset": 0},
        "result": [
            {
                "id": 1,
                "name": "1.0",
                "downloads": {"PAPER": {"downloadUrl": "https://cdn.example/a.jar"}},
                "platformDependencies": {"PAPER": ["1.20.6"]},
            }
        ],
    }
    with respx.mock:
        respx.get(f"{BASE}/projects/example/versions").mock(
            return_value=httpx.Response(200, json=payload)
        )
        versions = client.versions(
            "example", platform="PAPER", game_version="1.21.4"
        )

    assert versions == []


def test_http_error_is_reported(client: HangarClient) -> None:
    with respx.mock:
        respx.get(f"{BASE}/projects/example/versions").mock(
            return_value=httpx.Response(500)
        )
        with pytest.raises(ApiError, match="HTTP 500"):
            client.versions("example", platform="PAPER")
