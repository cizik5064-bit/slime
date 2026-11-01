from __future__ import annotations

import httpx
import pytest
import respx

from slime.api.papermc import PaperMCClient
from slime.errors import ApiError

BASE = "https://fill.example/v3"


@pytest.fixture
def client() -> PaperMCClient:
    return PaperMCClient(BASE, user_agent="Slime/test", timeout=5)


def test_projects_from_legacy_dict(client: PaperMCClient) -> None:
    payload = {
        "projects": {
            "paper": {"id": "paper", "name": "Paper"},
            "velocity": {"id": "velocity", "name": "Velocity"},
        }
    }
    with respx.mock:
        respx.get(f"{BASE}/projects").mock(
            return_value=httpx.Response(200, json=payload)
        )
        assert client.projects() == {"paper": "Paper", "velocity": "Velocity"}


def test_projects_from_current_list(client: PaperMCClient) -> None:
    payload = {
        "projects": [
            {"project": {"id": "paper", "name": "Paper"}, "versions": {}},
            {"project": {"id": "folia", "name": "Folia"}, "versions": {}},
            {"project": {"id": "travertine", "name": "Travertine"}, "versions": {}},
        ]
    }
    with respx.mock:
        respx.get(f"{BASE}/projects").mock(
            return_value=httpx.Response(200, json=payload)
        )
        assert client.projects() == {
            "paper": "Paper",
            "folia": "Folia",
            "travertine": "Travertine",
        }


def test_projects_from_list_of_strings(client: PaperMCClient) -> None:
    with respx.mock:
        respx.get(f"{BASE}/projects").mock(
            return_value=httpx.Response(200, json={"projects": ["paper", "folia"]})
        )
        assert client.projects() == {"paper": "paper", "folia": "folia"}


def test_versions_from_legacy_groups(client: PaperMCClient) -> None:
    payload = {"versions": {"1.21": ["1.21.4", "1.21.3"], "1.20": ["1.20.6"]}}
    with respx.mock:
        respx.get(f"{BASE}/projects/paper/versions").mock(
            return_value=httpx.Response(200, json=payload)
        )
        assert client.version_groups("paper") == payload["versions"]
        assert client.versions("paper") == ["1.21.4", "1.21.3", "1.20.6"]
        assert client.latest_version("paper") == "1.21.4"


def test_versions_from_current_object_list(client: PaperMCClient) -> None:
    payload = {
        "versions": [
            {
                "version": {"id": "26.3", "java": {"version": {"minimum": 25}}},
                "builds": [1, 2],
            },
            {
                "version": {"id": "1.21.4"},
                "builds": [232],
            },
        ]
    }
    with respx.mock:
        respx.get(f"{BASE}/projects/paper/versions").mock(
            return_value=httpx.Response(200, json=payload)
        )
        assert client.version_groups("paper") == {"all": ["26.3", "1.21.4"]}
        assert client.versions("paper") == ["26.3", "1.21.4"]


def test_versions_from_plain_list(client: PaperMCClient) -> None:
    with respx.mock:
        respx.get(f"{BASE}/projects/paper/versions").mock(
            return_value=httpx.Response(200, json=["1.21.4", "1.20.6"])
        )
        assert client.versions("paper") == ["1.21.4", "1.20.6"]


def test_empty_versions_raise(client: PaperMCClient) -> None:
    with respx.mock:
        respx.get(f"{BASE}/projects/paper/versions").mock(
            return_value=httpx.Response(200, json={"versions": []})
        )
        with pytest.raises(ApiError, match="no versions"):
            client.versions("paper")


def test_builds_are_parsed_and_sorted(client: PaperMCClient) -> None:
    payload = {
        "builds": [
            {
                "id": 43,
                "time": "2024-12-04T12:00:00Z",
                "channel": "BETA",
                "downloads": {
                    "server:default": {
                        "name": "paper-1.21.4-43.jar",
                        "checksums": {"sha256": "cafebabe"},
                        "size": 123,
                        "url": "https://example/43.jar",
                    }
                },
            },
            {
                "id": 42,
                "channel": "stable",
                "downloads": {
                    "server:default": {
                        "name": "paper-1.21.4-42.jar",
                        "checksums": {"sha256": "deadbeef"},
                        "size": 456,
                        "url": "https://example/42.jar",
                    }
                },
            },
        ]
    }
    with respx.mock:
        respx.get(f"{BASE}/projects/paper/versions/1.21.4/builds").mock(
            return_value=httpx.Response(200, json=payload)
        )
        builds = client.builds("paper", "1.21.4")
        assert [build.build for build in builds] == [42, 43]
        assert builds[0].channel == "STABLE"
        assert builds[0].server_download.sha256 == "deadbeef"
        assert builds[0].server_download.size == 456


def test_latest_build_respects_channel(client: PaperMCClient) -> None:
    payload = {
        "builds": [
            {"id": 1, "channel": "STABLE", "downloads": {}},
            {"id": 2, "channel": "BETA", "downloads": {}},
            {"id": 3, "channel": "BETA", "downloads": {}},
        ]
    }
    with respx.mock:
        respx.get(f"{BASE}/projects/paper/versions/1.21.4/builds").mock(
            return_value=httpx.Response(200, json=payload)
        )
        assert client.latest_build("paper", "1.21.4").build == 1
        assert client.latest_build("paper", "1.21.4", channel="STABLE").build == 1
        assert client.latest_build("paper", "1.21.4", channel="ANY").build == 3
        assert client.latest_build("paper", "1.21.4", channel="ALPHA").build == 3


def test_single_build(client: PaperMCClient) -> None:
    payload = {
        "id": 42,
        "channel": "STABLE",
        "downloads": {
            "server:default": {
                "name": "paper.jar",
                "url": "https://example/paper.jar",
            }
        },
    }
    with respx.mock:
        respx.get(f"{BASE}/projects/paper/versions/1.21.4/builds/42").mock(
            return_value=httpx.Response(200, json=payload)
        )
        build = client.build("paper", "1.21.4", 42)
        assert build.build == 42
        assert build.server_download.url == "https://example/paper.jar"


@pytest.mark.parametrize("status", [404, 403, 500])
def test_http_errors_raise_api_error(client: PaperMCClient, status: int) -> None:
    with respx.mock:
        respx.get(f"{BASE}/projects").mock(return_value=httpx.Response(status))
        with pytest.raises(ApiError):
            client.projects()


def test_network_error_raises_api_error(client: PaperMCClient) -> None:
    with respx.mock:
        respx.get(f"{BASE}/projects").mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(ApiError, match="Could not reach"):
            client.projects()


def test_invalid_json_raises_api_error(client: PaperMCClient) -> None:
    with respx.mock:
        respx.get(f"{BASE}/projects").mock(
            return_value=httpx.Response(200, text="not json")
        )
        with pytest.raises(ApiError, match="invalid JSON"):
            client.projects()


def test_build_missing_id_raises(client: PaperMCClient) -> None:
    with respx.mock:
        respx.get(f"{BASE}/projects/paper/versions/1.21.4/builds").mock(
            return_value=httpx.Response(200, json={"builds": [{"channel": "STABLE"}]})
        )
        with pytest.raises(ApiError, match="missing an id"):
            client.builds("paper", "1.21.4")


def test_context_manager_closes_owned_client() -> None:
    with PaperMCClient(BASE) as client:
        assert client.base_url == BASE
