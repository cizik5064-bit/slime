# Releasing Slime

This checklist is for maintainers preparing a public release. Slime follows
[Semantic Versioning](https://semver.org/): patch for bug fixes, minor for new
features, major for incompatible changes.

## One-time setup

1. Create the `slime-mc` project on [PyPI](https://pypi.org/) if it does not
   exist yet.
2. Configure **Trusted Publishing** on PyPI for the GitHub repository
   `cizik5064-bit/slime`, workflow `release.yml` and environment `pypi`.
3. In the GitHub repository, create an environment named `pypi`. Optionally add
   required reviewers so a release needs manual approval.

## Before tagging

1. Make sure `main` is green in CI (Windows and Linux, Python 3.11-3.14).
2. Update the version in both places; they must match:
   - `pyproject.toml` -> `[project].version`
   - `src/slime/__init__.py` -> `__version__`
3. Move the `[Unreleased]` entries in `CHANGELOG.md` under the new version and
   add the release date. Update the comparison links at the bottom.
4. Check that `README.md` still describes the released behaviour, commands and
   requirements.
5. Run the full local check:

   ```bash
   ruff check .
   mypy
   pytest
   ```

6. Build and inspect the artifacts:

   ```bash
   python -m build
   python -m twine check dist/*
   ```

   The `dist/` directory is ignored by git; delete old artifacts first.

7. Smoke-test the wheel in a fresh virtual environment:

   ```bash
   python -m venv /tmp/slime-release
   /tmp/slime-release/bin/pip install dist/slime_mc-<version>-py3-none-any.whl
   /tmp/slime-release/bin/slime --version
   /tmp/slime-release/bin/slime doctor
   ```

   On Windows use `.venv\Scripts\...` and a temporary path such as
   `$env:TEMP\slime-release`.

8. Commit the version bump with a message such as `chore: release 1.0.0`.

## Tag and publish

The `Release` workflow (`.github/workflows/release.yml`) runs on any `v*` tag.
It checks that the tag matches `pyproject.toml`, builds sdist and wheel,
publishes to PyPI through Trusted Publishing and creates a GitHub release with
generated notes.

```bash
git tag -a v1.0.0 -m "Slime 1.0.0"
git push origin main
git push origin v1.0.0
```

Do not tag if the version check would fail: the tag must be exactly
`v<pyproject version>`.

## After publishing

1. Watch the `Release` workflow and confirm both the PyPI upload and the GitHub
   release succeeded.
2. Verify the public install:

   ```bash
   pipx install --force slime-mc==1.0.0
   slime --version
   pipx uninstall slime-mc
   ```

3. Open a new `[Unreleased]` section in `CHANGELOG.md` if it is empty, and bump
   the version for ongoing development if needed.
4. Announce the release and close the corresponding milestone or issue.

## Manual fallback

If the workflow is unavailable, publish the already built and checked
artifacts manually:

```bash
python -m twine upload dist/*
```

Then create the GitHub release from the `v1.0.0` tag and attach the files from
`dist/`.
