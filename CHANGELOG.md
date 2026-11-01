# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/slime-mc/slime/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/slime-mc/slime/releases/tag/v1.0.0
