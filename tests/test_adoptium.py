from __future__ import annotations

import httpx
import pytest
import respx

from slime.api.adoptium import AdoptiumClient, current_arch, current_os
from slime.errors import ApiError

BASE = "https://adoptium.example/v3"


@pytest.fixture
def client() -> AdoptiumClient:
    return AdoptiumClient(BASE, user_agent="Slime/test", timeout=5)


def test_releases_and_lts(client: AdoptiumClient) -> None:
    payload = {
        "available_releases": [21, 8, 17, 25],
        "available_lts_releases": [21, 8, 17, 25],
    }
    with respx.mock:
        respx.get(f"{BASE}/info/available_releases").mock(
            return_value=httpx.Response(200, json=payload)
        )
        assert client.releases() == [8, 17, 21, 25]
        assert client.lts_releases() == [8, 17, 21, 25]


def test_releases_rejects_empty(client: AdoptiumClient) -> None:
    with respx.mock:
        respx.get(f"{BASE}/info/available_releases").mock(
            return_value=httpx.Response(200, json={"available_releases": []})
        )
        with pytest.raises(ApiError, match="no available"):
            client.releases()


def test_latest_package(client: AdoptiumClient) -> None:
    payload = [
        {
            "binary": {
                "os": "windows",
                "architecture": "x64",
                "package": {
                    "name": "OpenJDK21U-jdk_x64_windows_hotspot_21.0.4_7.zip",
                    "link": "https://example/temurin21.zip",
                    "checksum": "0123456789abcdef",
                    "size": 190000000,
                },
            },
            "version": {"semver": "21.0.4+7"},
        }
    ]
    with respx.mock:
        route = respx.get(f"{BASE}/assets/latest/21/hotspot").mock(
            return_value=httpx.Response(200, json=payload)
        )
        package = client.latest_package(21, os_name="windows", arch="x64")
        assert package.major == 21
        assert package.version == "21.0.4+7"
        assert package.name.endswith(".zip")
        assert package.url == "https://example/temurin21.zip"
        assert package.sha256 == "0123456789abcdef"
        assert package.size == 190000000
        assert route.called
        assert route.calls[0].request.url.params["os"] == "windows"
        assert route.calls[0].request.url.params["architecture"] == "x64"
        assert route.calls[0].request.url.params["image_type"] == "jdk"


def test_latest_package_accepts_checksum_object(client: AdoptiumClient) -> None:
    payload = [
        {
            "binary": {
                "package": {
                    "name": "temurin.zip",
                    "link": "https://example/temurin.zip",
                    "checksum": {"checksum": "abcdef"},
                }
            },
            "release": {"version": {"semver": "17.0.12+7"}},
        }
    ]
    with respx.mock:
        respx.get(f"{BASE}/assets/latest/17/hotspot").mock(
            return_value=httpx.Response(200, json=payload)
        )
        package = client.latest_package(17, os_name="linux", arch="x64")
        assert package.sha256 == "abcdef"
        assert package.version == "17.0.12+7"


def test_latest_package_without_assets(client: AdoptiumClient) -> None:
    with respx.mock:
        respx.get(f"{BASE}/assets/latest/21/hotspot").mock(
            return_value=httpx.Response(200, json=[])
        )
        with pytest.raises(ApiError, match="No Temurin"):
            client.latest_package(21, os_name="windows", arch="x64")


def test_latest_package_without_archive(client: AdoptiumClient) -> None:
    payload = [{"binary": {"installer": {"link": "https://example/installer.msi"}}}]
    with respx.mock:
        respx.get(f"{BASE}/assets/latest/21/hotspot").mock(
            return_value=httpx.Response(200, json=payload)
        )
        with pytest.raises(ApiError, match="none had an archive"):
            client.latest_package(21, os_name="windows", arch="x64")


def test_http_error(client: AdoptiumClient) -> None:
    with respx.mock:
        respx.get(f"{BASE}/info/available_releases").mock(
            return_value=httpx.Response(503)
        )
        with pytest.raises(ApiError, match="HTTP 503"):
            client.releases()


def test_current_platform_aliases() -> None:
    assert current_os() in {"windows", "linux", "mac"}
    assert current_arch() in {"x64", "aarch64", "arm", "x86"}
