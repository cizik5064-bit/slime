"""User-facing error types.

Every expected failure (bad input, network problem, missing Java, ...) is
raised as a :class:`SlimeError` subclass with an optional, actionable hint.
Unexpected exceptions are allowed to bubble up as real bugs.
"""

from __future__ import annotations


class SlimeError(Exception):
    """Base class for expected, user-facing errors."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class ConfigError(SlimeError):
    """The configuration file or Slime home directory is unusable."""


class ApiError(SlimeError):
    """A remote API returned an error or an unexpected payload."""


class DownloadError(SlimeError):
    """A download failed, was truncated, or failed checksum validation."""


class ArchiveError(SlimeError):
    """An archive could not be extracted safely."""


class JavaError(SlimeError):
    """A Java runtime is missing, unsupported, or could not be installed."""


class ServerError(SlimeError):
    """A server is missing, already running, or cannot be started."""


class BackupError(SlimeError):
    """A backup could not be created, read, restored, or deleted."""


class ValidationError(SlimeError):
    """A user-supplied value is invalid."""
