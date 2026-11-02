# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.1] - 2026-11-02

Patch release with fixes found in the first post-release audit.

### Fixed

- `slime java remove` no longer deletes the whole Java root when a runtime's
  metadata points at `~/.slime/java` itself.
- Broken `slime.json` records now raise a clear `SlimeError` instead of a
  traceback; invalid `extra_args`, `java_path`, `created_at` and numeric fields
  are normalized or reported as validation errors.
- Server exit codes are recorded reliably, so a crashed foreground server no
  longer exits Slime with status `0`.
- Velocity and Waterfall are stopped with `shutdown` and `end` respectively;
  Paper/Folia keep using `stop`.
- `slime server eula` no longer accepts the EULA by default. It asks
  interactively or requires `--accept` / `--revoke`.
- Values loaded from `config.toml` are range-validated (`default_port`,
  `default_memory_mb`, `default_java_major`).
- `server create` reports a conflict when the target path is a file instead of
  a directory.
- TUI delete/remove actions handle `OSError` and show a notification instead of
  crashing the worker.
- `JAVA_HOME` is set from the resolved Java installation home, not guessed from
  the executable path.
- Java installs for a non-host target OS look for `java.exe`/`java` correctly;
  archive extraction has a copy fallback when symlinks cannot be created.
- `ServerStore.is_running()` verifies the process working directory or command
  line, avoiding false positives from unrelated Java processes.
- Diagnostics no longer mention "Slime 0.1" and report a missing `server-port`
  clearly.
- Provisioning only removes directories it created itself when creation fails.
- The TUI create wizard no longer claims Java 21 for unknown ("latest")
  versions of calendar releases.
- The TUI server screen replays console lines emitted before it subscribed.

### Changed

- Development status classifier updated to `5 - Production/Stable`.

## [1.0.0] - 2026-11-02

First public release. This consolidates the 0.1.0 development series, which was
never published. Slime is distributed as `slime-mc` on PyPI and installs the
`slime` entry point.

### Added

- Full-screen Textual TUI: server dashboard, creation wizard, live console,
  Java manager and environment diagnostics.
- Typer CLI with commands for servers, Java runtimes, diagnostics and
  configuration.
- PaperMC Fill API v3 client for Paper, Folia, Velocity and Waterfall,
  including build channels (`STABLE`, `BETA`, `ALPHA`, `ANY`).
- Eclipse Adoptium API v3 client and Temurin Java manager: download, SHA-256
  verification, safe archive extraction and per-server runtime selection.
- Server provisioning: jar download, generated `server.properties` and
  `eula.txt`, port, memory and Java version defaults.
- Foreground server process management with streamed console output, command
  input, graceful stop and per-server logs.
- Environment checks (`slime doctor`): Python, OS, disk space, port conflicts,
  EULA, jar, Java and `server.properties` consistency, with a CI-friendly exit
  code.
- TOML configuration (`~/.slime/config.toml`) and `SLIME_HOME` / `--home`
  overrides.
- Test suite covering models, properties, config, store, checks, API clients,
  provisioning, process handling, CLI, archives, downloads and Java management.
- GitHub Actions CI for Windows and Linux on Python 3.11-3.14, plus a tagged
  release workflow that builds, publishes to PyPI and creates a GitHub release.
- Project infrastructure: MIT license, changelog, contribution guide, release
  checklist, `.gitignore` and `.gitattributes`.

### Changed

- Adapted the Fill API parsers to the 2026 response format while staying
  tolerant of the older shape.
- Calendar-based Minecraft versions `26.x+` now default to Java 25.
- Migrated TUI imports to Textual 2.x (`from textual import work`).
- API clients now derive their default `User-Agent` from the package version
  instead of hard-coding it.

### Fixed

- Removed a circular import between TUI screens and `SlimeApp`.
- `ServerStore.write_pid()` now creates the parent directory, so a PID file can
  be written before the server directory exists.
- Replaced `Enum` with `StrEnum`, typed bindings with `ClassVar`, and removed
  unsafe `try/except/pass` blocks; `ruff check .` and `mypy` are clean.

### Known limitations

- No cross-process `stop`: a server lives as long as the Slime process that
  started it. Stop it from the TUI, with `Ctrl+C`, or with the `stop` console
  command.
- Generated proxies (`velocity.toml`, `waterfall.yml`) must be configured
  manually.
- Windows 7 / 8 / 8.1 are not supported by this branch.

[Unreleased]: https://github.com/cizik5064-bit/slime/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/cizik5064-bit/slime/releases/tag/v1.0.0
