from __future__ import annotations

import io
import os
import tarfile
import zipfile
from pathlib import Path

import pytest

from slime.errors import ArchiveError
from slime.utils.archives import (
    extract_archive,
    find_java_executable,
    java_executable_name,
)


def test_java_executable_name_follows_target_os() -> None:
    assert java_executable_name("windows") == "java.exe"
    assert java_executable_name("linux") == "java"
    assert java_executable_name("mac") == "java"


def test_find_java_executable_uses_target_os(tmp_path: Path) -> None:
    executable = tmp_path / "jdk" / "bin" / "java.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")

    assert find_java_executable(tmp_path, os_name="windows") == executable
    assert find_java_executable(tmp_path, os_name="linux") is None


def make_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in members.items():
            bundle.writestr(name, data)
    return path


def make_tar(path: Path, members: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as bundle:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
    return path


def test_extract_zip(tmp_path: Path) -> None:
    archive = make_zip(
        tmp_path / "jdk.zip",
        {"jdk-21/bin/java": b"binary", "jdk-21/lib/modules": b"modules"},
    )
    destination = tmp_path / "out"
    extract_archive(archive, destination)
    assert (destination / "jdk-21" / "bin" / "java").read_bytes() == b"binary"
    assert (destination / "jdk-21" / "lib" / "modules").read_bytes() == b"modules"


def test_extract_tar_gz(tmp_path: Path) -> None:
    archive = make_tar(
        tmp_path / "jdk.tar.gz",
        {"jdk-21/bin/java": b"binary", "jdk-21/lib/modules": b"modules"},
    )
    destination = tmp_path / "out"
    extract_archive(archive, destination)
    assert (destination / "jdk-21" / "bin" / "java").read_bytes() == b"binary"


def test_zip_path_traversal_rejected(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "evil.zip", {"../escape.txt": b"no"})
    with pytest.raises(ArchiveError, match="escapes"):
        extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_tar_path_traversal_rejected(tmp_path: Path) -> None:
    archive = make_tar(tmp_path / "evil.tar.gz", {"../escape.txt": b"no"})
    with pytest.raises(ArchiveError, match="escapes"):
        extract_archive(archive, tmp_path / "out")


def test_unsupported_archive(tmp_path: Path) -> None:
    archive = tmp_path / "jdk.rar"
    archive.write_bytes(b"nope")
    with pytest.raises(ArchiveError, match="Unsupported"):
        extract_archive(archive, tmp_path / "out")


def test_invalid_zip(tmp_path: Path) -> None:
    archive = tmp_path / "broken.zip"
    archive.write_bytes(b"not a zip")
    with pytest.raises(ArchiveError, match="Could not extract"):
        extract_archive(archive, tmp_path / "out")


def test_find_java_executable_at_root_and_child(tmp_path: Path) -> None:
    executable = "java.exe" if os.name == "nt" else "java"
    root = tmp_path / "root"
    assert find_java_executable(root) is None

    (root / "bin").mkdir(parents=True)
    (root / "bin" / executable).write_text("", encoding="utf-8")
    assert find_java_executable(root) == root / "bin" / executable

    (root / "bin" / executable).unlink()
    child = root / "jdk-21" / "bin"
    child.mkdir(parents=True)
    (child / executable).write_text("", encoding="utf-8")
    assert find_java_executable(root) == child / executable
