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

> **Status: 1.9.1.** Core features are implemented and
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
- **Backups and restore** - create maximally compressed `.7z` snapshots of a
  stopped server (worlds, `config/`, the `plugins/` and/or `mods/` folders the
  loader supports, `logs/latest.log` and every root-level file except the
  server jar, Slime metadata and nested archives). Root files include
  `server.properties`, `eula.txt`, `ops.json`, `whitelist.json`,
  `banned-players.json`, `banned-ips.json`, `usercache.json`, `paper.json`,
  `bukkit.yml`, `spigot.yml` and any other per-server config.
  List, restore and delete them from `slime backup ...` or the **Backups**
  button on the server screen. The server jar and Slime metadata are never
  included.
- **Plugin and mod browser** - search Modrinth and Hangar for content that
  matches the server's Minecraft version and loader, then install it into
  `plugins/` or `mods/`. Required dependencies are resolved automatically,
  checksums are verified, and duplicate projects, file names or hashes are
  refused. Available from `slime content ...`; loading jars require a restart.
- **RCON console and cross-process control** - Slime enables Minecraft's RCON
  protocol for every non-proxy server with a random password and a port derived
  from the game port. Send commands to a server started by another Slime
  process (`slime server cmd`), attach an interactive console
  (`slime server console`) or stop it (`slime server stop`). The TUI recognizes
  servers started elsewhere, shows them as **external**, and routes commands and
  **Stop** through RCON. An explicit `enable-rcon=false` is always respected.
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
Get-FileHash .\slime-1.9.1-windows-x64.exe -Algorithm SHA256
.\slime-1.9.1-windows-x64.exe --version
.\slime-1.9.1-windows-x64.exe
```

Linux:

```bash
sha256sum -c slime-1.9.1-linux-x64.sha256
chmod +x slime-1.9.1-linux-x64
./slime-1.9.1-linux-x64 --version
./slime-1.9.1-linux-x64
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
slime backup create survival --note "before a plugin upgrade"
slime backup list survival
slime server cmd survival list
slime server console survival
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
Kill / Restart / Backups / Edit / Back buttons. **Backups** lists snapshots and
can create, restore or delete them; creating and restoring require a stopped
server. **Edit** opens the server editor with General, `server.properties` and
Dangerous tabs. **Delete** and **Reset world** live in **Dangerous** and require
holding Enter for five seconds. Servers started
from the TUI keep running while you navigate between screens, and are stopped
gracefully when you quit Slime. A server started by another process (another
Slime instance or a plain `java -jar`) is shown as **external**: the command
input and the Stop button use RCON, while Kill and Restart stay disabled. The
dashboard also has a **Stop** button for the selected server, including external
ones.

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
slime server cmd NAME COMMAND...
slime server console NAME
slime server stop NAME [--timeout SECONDS]
slime server versions [--project PROJECT] [--limit N] [--json]
slime server builds VERSION [--project PROJECT] [--channel CHANNEL] [--limit N] [--json]
```

### Backups

```text
slime backup create NAME [--note TEXT]
slime backup list [NAME] [--json]
slime backup restore NAME BACKUP [--yes]
slime backup delete NAME BACKUP [--yes]
slime backup path [NAME]
```

`BACKUP` is the archive id shown by `slime backup list` (a unique prefix is
enough). Create and restore require the server to be stopped so world files are
consistent. Restore replaces worlds, `config/`, and the `plugins/` and/or
`mods/` folders present in the archive, and
overwrites every root-level file from the archive, including `server.properties`,
`eula.txt`, `ops.json`, `whitelist.json`, `banned-players.json`,
`banned-ips.json`, `usercache.json`, `paper.json`, `bukkit.yml` and `spigot.yml`.
The server jar, `slime.json` and nested archives are preserved.
Deleting a backup removes the archive and its metadata sidecar only.

### Plugins and mods

```text
slime content search NAME QUERY [--source modrinth|hangar] [--kind plugin|mod] [--limit N]
slime content install NAME PROJECT [--source SOURCE] [--kind KIND]
                              [--version VERSION] [--no-deps] [--overwrite]
slime content list NAME [--json]
slime content remove NAME PROJECT [--yes]
```

`PROJECT` may be a Modrinth/Hangar slug, a project id or a search phrase.
Search and install are filtered by the server's Minecraft version and loader,
so incompatible releases never appear. Installation resolves required
dependencies recursively (use `--no-deps` to skip them), verifies the SHA-256
and SHA-512 hashes exposed by the source, and writes the jar to `plugins/` or
`mods/`. Duplicate projects, identical file names and matching hashes are
skipped unless `--overwrite` is passed.

What was installed is recorded in `slime-content.json` in the server directory,
which is also included in backups. Install and remove require the server to be
stopped; restart it to load new content. Hangar projects that only publish an
external download are rejected with a hint to install them manually.

### Remote control (RCON)

```text
slime server cmd NAME COMMAND [ARG ...]
slime server console NAME
slime server stop NAME [--timeout SECONDS]
```

`cmd` sends one command and prints the server's reply, `console` is an
interactive prompt (type `exit` to leave), and `stop` asks the server to shut
down and waits for its PID to disappear. All three work across processes, so
they can control a server started by the TUI or another terminal.

Slime enables RCON automatically for new non-proxy servers and whenever it
starts one: `enable-rcon=true`, `rcon.port` = game port + 10 (or 25575), and a
random `rcon.password` stored in `server.properties`. Existing values are kept,
and an explicit `enable-rcon=false` is never overridden. RCON changes need a
server restart to take effect.

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
  backups/
    <name>/
      <timestamp>.7z     # compressed server snapshot
      <timestamp>.json   # backup metadata (note, version, file count)
  logs/
    slime.log
    <server>.log         # full console log per server
```

`server.properties` is only created if it is missing: existing user values are
preserved. Slime warns when the port in `server.properties` disagrees with the
port recorded in `slime.json`. For non-proxy servers Slime also keeps
`enable-rcon`, `rcon.port` and `rcon.password` set so another process can use
`slime server cmd`, `slime server console` and `slime server stop`.

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
- [x] Backups and restore
- [x] Plugin/mod browser (Modrinth / Hangar)
- [x] RCON console and cross-process server control
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
