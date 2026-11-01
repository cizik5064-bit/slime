# Contributing to Slime

Thanks for taking the time to help. Slime is a small project, so clear reports
and focused pull requests are very welcome.

## Before you start

- For bugs, open an issue with the Slime version (`slime --version`), your OS,
  Python version and the exact command you ran. Include relevant lines from
  `~/.slime/logs/slime.log`. Never paste tokens, passwords or other secrets.
- For features, open an issue first so we can agree on the scope before you
  spend time on code.
- Report security problems privately to the maintainers instead of opening a
  public issue.

## Development setup

Requirements: Python 3.11+ and git.

```bash
git clone https://github.com/slime-mc/slime.git
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

Run the app from the checkout with `slime` or `python -m slime`. Use a temporary
home directory when experimenting so your real servers are not touched:

```powershell
$env:SLIME_HOME = "$env:TEMP\slime-dev"
slime doctor
```

## Checks

Every change must keep these commands green:

```bash
ruff check .
mypy
pytest
```

`pytest` and the linters run in CI on Windows and Linux for Python 3.11 through
3.14. Tests must not depend on network access; use `respx` and the fixtures in
`tests/fixtures` for HTTP clients.

## Code style

- Code, identifiers, UI strings, docstrings and documentation are in English.
- Keep the existing layout: API clients return dataclasses, provisioning is
  separate from process management, and the TUI only orchestrates services.
- Add type hints to public functions. Prefer small, testable modules.
- Do not add dependencies without discussing it in an issue first.
- Never accept the Minecraft EULA on the user's behalf.
- Do not log secrets, tokens or personal data.

## Tests

- Add or update tests for every behaviour change.
- Put shared fixtures in `tests/conftest.py`, keep network fixtures in
  `tests/fixtures/`.
- A bug fix should include a regression test that fails before the fix.

## Commits and pull requests

- Use short imperative commit subjects, for example
  `fix: create PID parent directory` or `feat: add Java 25 defaults`.
- Keep pull requests focused; unrelated refactors belong in a separate PR.
- Describe what changed, why, and how you tested it. Mention the OS and Python
  version if the change is platform-specific.
- Update `CHANGELOG.md` under `[Unreleased]` for user-visible changes.
- Update `README.md` when behaviour, commands or requirements change.

## Versioning

Before `1.0.0`, versions are bumped at the maintainer's discretion. After the
first public release, every user-visible change bumps the version in
`pyproject.toml` and `src/slime/__init__.py`, and adds a `CHANGELOG.md` entry:

- patch for bug fixes and small changes;
- minor for new functionality;
- major for incompatible changes.

## License

By contributing, you agree that your contribution is licensed under the MIT
License (see `LICENSE`).
