"""Streaming downloads with progress reporting and checksum verification."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path

import httpx

from ..errors import DownloadError

ProgressCallback = Callable[[int, int | None], None]

DEFAULT_CHUNK_SIZE = 1024 * 1024


def _hash_file(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(DEFAULT_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(
    path: Path,
    *,
    sha256: str | None = None,
    size: int | None = None,
) -> None:
    """Raise :class:`DownloadError` when a file does not match expectations."""
    if not path.exists():
        raise DownloadError(f"File is missing: {path}")
    if size is not None and path.stat().st_size != size:
        raise DownloadError(
            f"Wrong file size for {path.name}: expected {size} bytes, "
            f"got {path.stat().st_size}."
        )
    if sha256:
        actual = _hash_file(path)
        if actual.lower() != sha256.lower():
            raise DownloadError(
                f"Checksum mismatch for {path.name}.",
                hint=f"Expected {sha256}, got {actual}. Delete the file and retry.",
            )


def download_file(
    url: str,
    destination: Path,
    *,
    sha256: str | None = None,
    size: int | None = None,
    user_agent: str | None = None,
    timeout: float = 60.0,
    progress: ProgressCallback | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overwrite: bool = True,
) -> Path:
    """Download ``url`` to ``destination`` atomically.

    The file is written to ``<destination>.part`` first and only moved into
    place after the size and (optional) SHA-256 checks pass.
    """
    destination = destination.expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists() and not overwrite:
        try:
            verify_file(destination, sha256=sha256, size=size)
        except DownloadError:
            pass
        else:
            if progress:
                existing_size = destination.stat().st_size
                progress(existing_size, existing_size)
            return destination

    temporary = destination.with_name(destination.name + ".part")
    temporary.unlink(missing_ok=True)
    headers = {"User-Agent": user_agent} if user_agent else {}
    downloaded = 0

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers=headers,
        ) as client, client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise DownloadError(
                    f"Download failed with HTTP {response.status_code}: {url}",
                    hint="Check your internet connection or try again later.",
                )
            content_length = response.headers.get("content-length")
            total: int | None = (
                int(content_length)
                if content_length and content_length.isdigit()
                else None
            )
            if progress:
                progress(0, total)
            with temporary.open("wb") as handle:
                for chunk in response.iter_bytes(chunk_size):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if progress:
                        progress(downloaded, total)
    except DownloadError:
        temporary.unlink(missing_ok=True)
        raise
    except (httpx.HTTPError, OSError) as exc:
        temporary.unlink(missing_ok=True)
        raise DownloadError(
            f"Could not download {url}: {exc}",
            hint="Check your internet connection, proxy, or firewall settings.",
        ) from exc

    try:
        verify_file(temporary, sha256=sha256, size=size)
        os.replace(temporary, destination)
    except DownloadError:
        temporary.unlink(missing_ok=True)
        raise

    if progress:
        progress(downloaded, downloaded)
    return destination
