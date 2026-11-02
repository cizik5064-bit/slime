"""Safe archive extraction for Temurin JDK packages."""

from __future__ import annotations

import os
import shutil
import tarfile
import zipfile
from pathlib import Path

from ..errors import ArchiveError


def _safe_target(root: Path, member_name: str) -> Path:
    root = root.resolve()
    target = (root / member_name).resolve()
    if target != root and root not in target.parents:
        raise ArchiveError(
            f"Archive member escapes the destination: {member_name!r}",
            hint="The archive is unsafe. Do not extract it manually.",
        )
    return target


def _extract_zip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            target = _safe_target(destination, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)
            mode = (info.external_attr >> 16) & 0o777
            if mode and os.name != "nt":
                target.chmod(mode)


def _extract_tar(archive: Path, destination: Path) -> None:
    pending_links: list[tuple[Path, str, bool]] = []
    with tarfile.open(archive, "r:*") as bundle:
        for member in bundle.getmembers():
            target = _safe_target(destination, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.issym() or member.islnk():
                # JDK archives contain a few internal symlinks. Keep them only
                # when the link target stays inside the extraction root.
                _safe_target(target.parent, member.linkname)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    target.unlink()
                try:
                    os.symlink(
                        member.linkname, target, target_is_directory=member.isdir()
                    )
                except OSError:
                    # Creating symlinks needs extra privileges on Windows.
                    # Defer and copy the target file if it exists.
                    pending_links.append((target, member.linkname, member.isdir()))
                continue
            if not member.isfile():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                continue
            with source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)
            if member.mode and os.name != "nt":
                target.chmod(member.mode & 0o777)

    for target, linkname, is_directory in pending_links:
        if is_directory:
            continue
        link_source = (target.parent / linkname).resolve()
        try:
            link_source.relative_to(destination.resolve())
        except ValueError:
            continue
        if link_source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(link_source, target)


def extract_archive(archive: Path, destination: Path) -> None:
    """Extract a ``.zip``, ``.tar.gz``/``.tgz`` or ``.tar`` archive safely."""
    destination.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    try:
        if name.endswith(".zip"):
            _extract_zip(archive, destination)
        elif name.endswith((".tar.gz", ".tgz", ".tar")):
            _extract_tar(archive, destination)
        else:
            raise ArchiveError(
                f"Unsupported archive format: {archive.name}",
                hint="Slime supports .zip, .tar.gz and .tar archives.",
            )
    except ArchiveError:
        raise
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise ArchiveError(f"Could not extract {archive.name}: {exc}") from exc


def java_executable_name(os_name: str | None = None) -> str:
    """Return the Java executable file name for a target OS.

    ``None`` means the OS Slime is currently running on. Adoptium uses
    ``windows``, ``linux`` and ``mac`` as OS names.
    """
    if os_name is None:
        return "java.exe" if os.name == "nt" else "java"
    return "java.exe" if os_name.lower() in {"windows", "win", "nt"} else "java"


def find_java_executable(root: Path, *, os_name: str | None = None) -> Path | None:
    """Find ``bin/java`` (or ``bin/java.exe``) at or one level below ``root``."""
    executable = java_executable_name(os_name)
    candidates = [root / "bin" / executable]
    if root.is_dir():
        candidates += [child / "bin" / executable for child in root.iterdir() if child.is_dir()]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None
