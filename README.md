# Slime

<p align="center">
  <a href="https://github.com/cizik5064-bit/slime/actions/workflows/release.yml"><img src="https://github.com/cizik5064-bit/slime/actions/workflows/release.yml/badge.svg" alt="Release"></a>
  <a href="https://github.com/cizik5064-bit/slime/actions/workflows/ci.yml"><img src="https://github.com/cizik5064-bit/slime/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/slime-mc/"><img src="https://img.shields.io/pypi/v/slime-mc.svg" alt="PyPI"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+"></a>
</p>

<p align="center">
  <a href="https://github.com/cizik5064-bit/slime/actions/workflows/ci.yml"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/cizik5064-bit/slime/badges/coverage.json" alt="Coverage"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff"></a>
  <a href="https://mypy-lang.org/"><img src="https://www.mypy-lang.org/static/mypy_badge.svg" alt="Checked with mypy"></a>
</p>

<p align="center">
  <a href="https://pypi.org/project/slime-mc/"><img src="https://img.shields.io/pypi/dm/slime-mc.svg" alt="PyPI Downloads"></a>
  <a href="https://pepy.tech/project/slime-mc"><img src="https://static.pepy.tech/badge/slime-mc" alt="PyPI Total Downloads"></a>
  <a href="https://github.com/cizik5064-bit/slime/stargazers"><img src="https://img.shields.io/github/stars/cizik5064-bit/slime" alt="GitHub stars"></a>
  <a href="https://github.com/cizik5064-bit/slime/network"><img src="https://img.shields.io/github/forks/cizik5064-bit/slime" alt="GitHub forks"></a>
  <a href="https://github.com/cizik5064-bit/slime/issues"><img src="https://img.shields.io/github/issues/cizik5064-bit/slime" alt="GitHub issues"></a>
  <a href="https://github.com/cizik5064-bit/slime/graphs/contributors"><img src="https://img.shields.io/github/contributors/cizik5064-bit/slime" alt="Contributors"></a>
</p>

<p align="center">
  <a href="https://github.com/cizik5064-bit/slime/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/platform-windows%20%7C%20linux-lightgrey" alt="Platform: Windows | Linux">
  <img src="https://img.shields.io/badge/minecraft-paper%20%7C%20folia%20%7C%20velocity%20%7C%20waterfall-blue" alt="Minecraft: Paper | Folia | Velocity | Waterfall">
</p>

**A friendly Minecraft server manager for humans, not sysadmins.**

Slime is a Python application with a full-screen terminal UI (TUI) and a
scriptable CLI. It helps beginners create, configure, run and troubleshoot
Minecraft servers without hunting for jars, Java versions or API URLs.

> **Status: 1.6.0.** Core features are implemented and
> covered by tests, but Slime is still young. Expect rough edges and please
> report them on the issue tracker.

---

## Why Slime?

Setting up a Minecraft server usually involves five different websites, a Java
version you did not know you needed, a EULA you have never read, and a port
that is already in use. Slime turns that into a guided flow:

```text
slime java install 21
slime server create survival --project paper --memory 4096 --accept-eula
slime server run survival
```

Or just run `slime` and use the TUI.

## Features

- **PaperMC Fill API v3** - download the latest builds of Paper, Folia,
  Velocity and Waterfall directly from the official API. No scraping, no
  BuildTools.
- **Purpur support** - Purpur builds come straight from the official
  [Purpur API v2](https://api.purpurmc.org/v2/purpur), with versions and builds
  listed alongside the PaperMC projects.
- **Temurin Java manager** - install the exact Eclipse Adoptium JDK a server
  needs (8, 11, 16, 17, 21, 25), per platform and architecture. Slime downloads
  the archive, verifies the SHA-256 checksum, extracts it into `~/.slime/java`
  and records the exact `bin/java` path.
- **TUI + CLI** - a Textual interface for browsing servers, editing settings,
  watching the console live and sending commands; a Typer CLI for automation.
- **Server editor** - change the server name, min/max RAM, launch flags,
  garbage collector (G1GC, ZGC, Shenandoah, Parallel or Serial), CPU core
  allocation, Java path/version, and every `server.properties` value from one
  screen. New servers start with Aikar's performant flags in the editable
  **Launch flags** box; RAM, CPU cores, `nogui` and recovery flags stay managed
  by Slime. Destructive actions live in a separate **Dangerous** tab:
  **Reset world** and **Delete server** both require holding Enter for five
  seconds.
- **Safer crash recovery** - servers that exit with an exception or a non-zero
  status are reported as **crashed**. If the crash points to a damaged world
  (`Overworld settings missing`, a corrupt `level.dat`, or a similar error),
  Slime offers to reset the world the next time the server starts. Recovery
  flags such as `--safeMode` apply to one launch only and are never saved.
- **Server lifecycle** - create, start, stop, restart, delete and inspect
  servers. A foreground console streams logs and accepts commands via stdin.
  A deliberate stop or kill stays **stopped**, and the console shows Slime's
  own actions (`[slime] Stopping server...`, `[slime] Server stopped.`).
- **Environment checks** - Python, OS, disk space, available RAM, port
  conflicts, EULA status, server jar, `server.properties` consistency and Java
  availability.
- **Beginner-friendly defaults** - sensible `server.properties`, MOTD, port,
  memory and Java version detection; clear error messages with actionable hints.
- **Windows Terminal on Windows** - when started from `cmd.exe` or an older
  PowerShell window, the TUI reopens itself in Windows Terminal for correct
  Unicode rendering. If Windows Terminal is missing, Slime tries to install it
  with `winget`. Set `SLIME_NO_WINDOWS_TERMINAL=1` to opt out.
- **Cross-platform** - Windows 10+ and Linux (macOS works but is not a primary
  target). Windows 7/8/8.1 will require a separate legacy build; see
  [Platform support](#platform-support).
- **Local-first** - everything lives in `~/.slime` by default. No account, no
  telemetry, no cloud.

## Supported projects

| Project | Kind | API | Java (by default) |
| --- | --- | --- | --- |
| Paper | Server | [Fill v3](https://fill.papermc.io/v3) | 21 for 1.20.5+, 17 for 1.17-1.20.4, 8 for ≤1.16.5 |
| Folia | Server | Fill v3 | same as Paper |
| Purpur | Server | [Purpur v2](https://api.purpurmc.org/v2/purpur) | same as Paper |
| Velocity | Proxy | Fill v3 | 17 |
| Waterfall | Proxy | Fill v3 | 11 |

Slime only uses the official download APIs for these five projects. Spigot,
Forge, NeoForge and Fabric are not supported yet.

Proxies generate their own `velocity.toml` / `waterfall.yml` on first start.
Slime prepares the directory and jar, then leaves proxy networking config to
you.

## Requirements

- **Python 3.11+**
- **Windows 10+** or **Linux** (x86-64 or ARM64)
- Internet access for the first setup (PaperMC, Purpur and Adoptium APIs)
- At least 1 GiB of free disk space; 5 GiB+ recommended

## Installation

Slime requires Python 3.11 or newer.

The recommended way is an isolated installation with
[pipx](https://pipx.pypa.io/):

```bash
pipx install slime-mc
```

Or install it into the current environment with pip:

```bash
pip install slime-mc
```

Run it:

```bash
slime --version
slime
```

### Standalone executables (Windows and Linux)

Every tagged release includes a self-contained executable and a matching
`.sha256` checksum on the
[GitHub Releases](https://github.com/cizik5064-bit/slime/releases) page:

- `slime-<version>-windows-x64.exe`
- `slime-<version>-linux-x64`

They bundle Python and all dependencies, so no separate Python installation is
needed.

Windows:

```powershell
Get-FileHash .\slime-1.6.0-windows-x64.exe -Algorithm SHA256
.\slime-1.6.0-windows-x64.exe --version
.\slime-1.6.0-windows-x64.exe
```

Linux:

```bash
sha256sum -c slime-1.6.0-linux-x64.sha256
chmod +x slime-1.6.0-linux-x64
./slime-1.6.0-linux-x64 --version
./slime-1.6.0-linux-x64
```

Compare the hash with the published `.sha256` file before running the binary.
Both executables use the same `~/.slime` home directory as the Python install.

### From source (development)

```bash
git clone https://github.com/cizik5064-bit/slime.git
cd slime
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow.

To build the standalone executable locally:

```bash
python -m pip install -e ".[build]"
python scripts/build_exe.py
```

The binary and its checksum are written to `dist/`.

## Quick start (CLI)

```bash
# 1. Install the Java version the server needs
slime java install 21

# 2. Create a Paper server using the latest Minecraft version
slime server create survival --project paper --memory 4096 --accept-eula

# 3. Start it in the foreground and attach the console
slime server run survival
```

Inside the console, type Minecraft commands (`op Notch`, `say hello`, `stop`).
Press **Ctrl+C** to stop the server gracefully.

Useful follow-ups:

```bash
slime server list
slime server info survival --checks
slime doctor
slime server versions --project paper
slime server builds 1.21.4 --project paper
```

Choosing a version and build explicitly:

```bash
slime server create creative \
  --project paper \
  --version 1.21.4 \
  --channel STABLE \
  --memory 6144 \
  --port 25566 \
  --accept-eula
```

## Quick start (TUI)

```bash
slime
```

| Key | Action |
| --- | --- |
| `n` | New server |
| `j` | Java manager |
| `d` | Doctor (environment checks) |
| `r` | Refresh |
| `q` | Quit (stops servers started by the TUI) |
| `Enter` | Open the selected server |
| `Esc` | Back |

The server screen shows live console output, a command input, and Start / Stop /
Kill / Restart / Edit / Back buttons. **Edit** opens the server editor with
General, `server.properties` and Dangerous tabs. **Delete** and **Reset world**
live in **Dangerous** and require holding Enter for five seconds. Servers started
from the TUI keep running while you navigate between screens, and are stopped
gracefully when you quit Slime.

## Commands

### Global

```text
slime [--home PATH] [--verbose] [--version]
slime tui
slime doctor [--server NAME] [--json]
```

With no arguments, `slime` opens the TUI when stdout is a terminal.

### Servers

```text
slime server list [--json]
slime server create NAME [--project paper|folia|purpur|velocity|waterfall]
                          [--version VERSION] [--build N] [--channel STABLE|BETA|ALPHA|ANY]
                          [--memory MB] [--port PORT] [--java MAJOR]
                          [--motd TEXT] [--accept-eula]
slime server info NAME [--checks] [--json]
slime server run NAME [--memory MB] [--java PATH] [--no-console]
slime server eula NAME [--accept/--revoke]
slime server delete NAME [--yes] [--keep-files]
slime server path NAME
slime server versions [--project PROJECT] [--limit N] [--json]
slime server builds VERSION [--project PROJECT] [--channel CHANNEL] [--limit N] [--json]
```

### Java

```text
slime java list [--json]
slime java releases [--json]
slime java install MAJOR [--force] [--os OS] [--arch ARCH]
slime java remove MAJOR [--yes]
slime java which [MAJOR] [--server NAME]
```

### Configuration

```text
slime config show [--json]
slime config set KEY VALUE
slime config path
```

Editable settings: `default_memory_mb`, `default_java_major`, `default_port`,
`accept_eula_default`.

## How Java selection works

Each server records the Java **major** it needs. Slime resolves it in this
order:

1. An explicit `java_path` on the server (set with `slime server run --java`).
2. A Temurin runtime managed by Slime with the same major
   (`~/.slime/java/temurin-<major>-<os>-<arch>`).
3. A system Java found on `PATH` or via `JAVA_HOME`, but only if its major
   matches exactly.

If nothing matches, Slime tells you exactly what to run:

```text
Error: Java 21 is required by survival (Paper 1.21.4), but it is not installed.
Hint: Install it with: slime java install 21
```

Install specific runtimes with:

```bash
slime java install 17
slime java install 21
slime java list
```

Slime never installs a JDK silently. It also never overwrites `eula=true`
without explicit confirmation (`--accept-eula` or an interactive prompt).

## Where files live

Default home: `~/.slime` (override with `SLIME_HOME` or `--home`).

```text
~/.slime/
  config.toml            # settings
  servers/
    <name>/
      slime.json         # Slime metadata (project, build, Java, port, RAM)
      server.jar         # downloaded PaperMC jar
      server.properties  # generated for servers
      eula.txt           # generated for servers
      world/             # created by Minecraft on first start
  java/
    temurin-21-windows-x64/
      bin/java.exe
      slime-java.json
  cache/                 # temporary downloads
  logs/
    slime.log
    <server>.log         # full console log per server
```

`server.properties` is only created if it is missing: existing user values are
preserved. Slime warns when the port in `server.properties` disagrees with the
port recorded in `slime.json`.

## Environment checks

`slime doctor` (or `d` in the TUI) reports:

- Python version (3.11+)
- Operating system (Windows 10+, Linux, macOS)
- Writable Slime home directory
- Free disk space (error below 1 GiB, warning below 5 GiB)
- Per server: jar, Java runtime, EULA, port, RAM, `server.properties` port
- Installed Java runtimes

Exit code `2` means at least one check failed, which makes it usable in CI.

## Platform support

| Platform | Status |
| --- | --- |
| Windows 10 / 11 | Primary target |
| Linux x86-64 | Primary target |
| Linux ARM64 | Supported by Adoptium; lightly tested |
| macOS | Should work, not a primary target |
| Windows 8.1 | Not supported by Python 3.11+ |
| Windows 7 / 8 | Needs a separate legacy build (Python 3.8, older Textual) |

Windows 7 and 8/8.1 support cannot be added to this codebase: Python 3.9+ and
modern Textual do not run there. A future `0.x-legacy` build may target Python
3.8 with pinned dependencies. Until then, Slime prints a clear compatibility
error on unsupported Windows versions.

### Windows Terminal

The classic Windows console host can garble the box-drawing and progress
characters used by the TUI. When Slime starts interactively from such a console,
it opens a new **Windows Terminal** tab and exits the original process. If
`wt.exe` is not installed, Slime runs:

```powershell
winget install --id Microsoft.WindowsTerminal --exact --silent `
  --accept-source-agreements --accept-package-agreements
```

The relaunch is skipped when Slime already runs inside Windows Terminal, when
stdin/stdout are not interactive, or when `SLIME_NO_WINDOWS_TERMINAL` is set to
any non-empty value. It applies only to the TUI, not to scriptable CLI commands.

## Development

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

ruff check .
pytest
```

Project layout:

```text
src/slime/
  cli.py            # Typer commands
  tui/              # Textual app, screens, CSS
  api/papermc.py    # Fill API v3 client
  api/purpur.py     # Purpur API v2 client
  api/catalog.py    # routes a project to its download API
  api/adoptium.py   # Adoptium API v3 client
  java.py           # Temurin install/discovery
  provision.py      # create-server flow
  process.py        # server process + console
  checks.py         # environment checks
  store.py          # ~/.slime/server registry
  models.py         # data models and validation
  properties.py     # server.properties / eula.txt
tests/              # pytest suite (in progress)
```

The design favours explicit, testable modules: API clients return dataclasses,
provisioning is separated from process management, and the TUI only orchestrates
services.

## Roadmap

- [x] Core architecture, models and validation
- [x] Fill API v3 client (Paper, Folia, Velocity, Waterfall)
- [x] Purpur API v2 client
- [x] Adoptium Temurin client and Java manager
- [x] CLI (servers, Java, diagnostics, config)
- [x] Textual TUI (dashboard, server console, create wizard, Java, doctor)
- [x] Server settings editor (General, server.properties, Dangerous)
- [x] Full test suite and CI on Windows + Linux
- [x] First public release (1.0.0)
- [x] Packaging on PyPI (`slime-mc`)
- [ ] Backups and restore
- [ ] Plugin/mod browser (Modrinth / Hangar)
- [ ] RCON console and cross-process server control
- [ ] Legacy Windows 7/8.1 build
- [x] Standalone Windows executable via Nuitka

## Disclaimer

Slime is an unofficial community project. It is not affiliated with Mojang,
Microsoft, PaperMC, or Eclipse Adoptium. Minecraft is a trademark of Mojang
Studios. By creating a server you agree to the
[Minecraft EULA](https://aka.ms/MinecraftEULA); Slime only records your
explicit acceptance and never accepts it for you.

## License

MIT - see [LICENSE](LICENSE).
