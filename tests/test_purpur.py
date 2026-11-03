from __future__ import annotations

import httpx
import pytest
import respx

from slime.api.purpur import PurpurClient
from slime.errors import ApiError

BASE = "https://purpur.example/v2/purpur"


@pytest.fixture
def client() -> PurpurClient:
    return PurpurClient(BASE, user_agent="Slime/test", timeout=5)


def test_versions_are_sorted(client: PurpurClient) -> None:
    payload = {"project": "purpur", "versions": ["1.20.6", "26.3", "1.21.8"]}
    with respx.mock:
        respx.get(BASE).mock(return_value=httpx.Response(200, json=payload))
        assert client.versions() == ["26.3", "1.21.8", "1.20.6"]
        assert client.latest_version() == "26.3"


def test_empty_versions_raise(client: PurpurClient) -> None:
    with respx.mock:
        respx.get(BASE).mock(
            return_value=httpx.Response(200, json={"versions": []})
        )
        with pytest.raises(ApiError, match="no versions"):
            client.versions()


def test_builds_are_parsed_and_sorted(client: PurpurClient) -> None:
    payload = {
        "project": "purpur",
        "version": "1.21.8",
        "builds": {"latest": "2497", "all": ["2497", "2495", "2496"]},
    }
    with respx.mock:
        respx.get(f"{BASE}/1.21.8").mock(
            return_value=httpx.Response(200, json=payload)
        )
        builds = client.builds("purpur", "1.21.8")

    assert [build.build for build in builds] == [2495, 2496, 2497]
    assert all(build.project == "purpur" for build in builds)
    assert builds[-1].server_download.url == f"{BASE}/1.21.8/2497/download"
    assert builds[-1].server_download.name == "purpur-1.21.8-2497.jar"


def test_single_build_includes_timestamp(client: PurpurClient) -> None:
    payload = {
        "project": "purpur",
        "version": "1.21.8",
        "build": "2497",
        "result": "SUCCESS",
        "timestamp": 1758246365352,
    }
    with respx.mock:
        respx.get(f"{BASE}/1.21.8/2497").mock(
            return_value=httpx.Response(200, json=payload)
        )
        build = client.build("purpur", "1.21.8", 2497)

    assert build.build == 2497
    assert build.time == "2025-09-19T01:46:05+00:00"


def test_latest_build_uses_latest_endpoint(client: PurpurClient) -> None:
    payload = {
        "project": "purpur",
        "version": "1.21.8",
        "build": "2497",
        "result": "SUCCESS",
        "timestamp": 1758246365352,
    }
    with respx.mock:
        route = respx.get(f"{BASE}/1.21.8/latest").mock(
            return_value=httpx.Response(200, json=payload)
        )
        build = client.latest_build("purpur", "1.21.8")

    assert route.called
    assert build.build == 2497
    assert build.server_download.url == f"{BASE}/1.21.8/2497/download"


def test_failed_build_raises(client: PurpurClient) -> None:
    payload = {
        "project": "purpur",
        "version": "1.21.8",
        "build": "2497",
        "result": "FAILURE",
    }
    with respx.mock:
        respx.get(f"{BASE}/1.21.8/2497").mock(
            return_value=httpx.Response(200, json=payload)
        )
        with pytest.raises(ApiError, match="FAILURE"):
            client.build("purpur", "1.21.8", 2497)


@pytest.mark.parametrize("status", [404, 429, 500])
def test_http_errors_raise_api_error(client: PurpurClient, status: int) -> None:
    with respx.mock:
        respx.get(BASE).mock(return_value=httpx.Response(status))
        with pytest.raises(ApiError):
            client.versions()


def test_network_error_raises_api_error(client: PurpurClient) -> None:
    with respx.mock:
        respx.get(BASE).mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(ApiError, match="Could not reach"):
            client.versions()


def test_invalid_json_raises_api_error(client: PurpurClient) -> None:
    with respx.mock:
        respx.get(BASE).mock(
            return_value=httpx.Response(200, content=b"not json")
        )
        with pytest.raises(ApiError, match="invalid JSON"):
            client.versions()
