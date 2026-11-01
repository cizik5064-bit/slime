from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
import respx

from slime.errors import DownloadError
from slime.utils.downloads import download_file, verify_file

URL = "https://example.test/file.bin"
DATA = b"hello download"
SHA256 = hashlib.sha256(DATA).hexdigest()


def test_download_success(tmp_path: Path) -> None:
    destination = tmp_path / "file.bin"
    progress: list[tuple[int, int | None]] = []
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(200, content=DATA))
        result = download_file(
            URL,
            destination,
            sha256=SHA256,
            size=len(DATA),
            progress=lambda done, total: progress.append((done, total)),
        )
    assert result == destination
    assert destination.read_bytes() == DATA
    assert not destination.with_name(destination.name + ".part").exists()
    assert progress[-1] == (len(DATA), len(DATA))


def test_download_checksum_mismatch(tmp_path: Path) -> None:
    destination = tmp_path / "file.bin"
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(200, content=DATA))
        with pytest.raises(DownloadError, match="Checksum mismatch"):
            download_file(URL, destination, sha256="0" * 64)
    assert not destination.exists()
    assert not destination.with_name(destination.name + ".part").exists()


def test_download_size_mismatch(tmp_path: Path) -> None:
    destination = tmp_path / "file.bin"
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(200, content=DATA))
        with pytest.raises(DownloadError, match="Wrong file size"):
            download_file(URL, destination, size=len(DATA) + 1)
    assert not destination.exists()


def test_download_http_error(tmp_path: Path) -> None:
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(404))
        with pytest.raises(DownloadError, match="HTTP 404"):
            download_file(URL, tmp_path / "file.bin")


def test_download_network_error(tmp_path: Path) -> None:
    with respx.mock:
        respx.get(URL).mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(DownloadError, match="Could not download"):
            download_file(URL, tmp_path / "file.bin")


def test_download_reuses_valid_file_when_not_overwriting(tmp_path: Path) -> None:
    destination = tmp_path / "file.bin"
    destination.write_bytes(DATA)
    with respx.mock:
        result = download_file(
            URL, destination, sha256=SHA256, size=len(DATA), overwrite=False
        )
    assert result == destination
    assert destination.read_bytes() == DATA


def test_download_redownloads_invalid_file_when_not_overwriting(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "file.bin"
    destination.write_bytes(b"old")
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(200, content=DATA))
        download_file(
            URL, destination, sha256=SHA256, size=len(DATA), overwrite=False
        )
    assert destination.read_bytes() == DATA


def test_verify_file_checks_size_and_hash(tmp_path: Path) -> None:
    path = tmp_path / "file.bin"
    path.write_bytes(DATA)
    verify_file(path, size=len(DATA), sha256=SHA256)
    with pytest.raises(DownloadError):
        verify_file(path, size=1)
    with pytest.raises(DownloadError):
        verify_file(path, sha256="0" * 64)
    with pytest.raises(DownloadError):
        verify_file(tmp_path / "missing.bin")
