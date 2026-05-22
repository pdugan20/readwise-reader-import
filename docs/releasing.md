# Releasing

Releases are automated with
[release-please](https://github.com/googleapis/release-please).

## How it works

1. Merge changes to `main` using [Conventional Commits](https://www.conventionalcommits.org/)
   (`feat:`, `fix:`, etc.).
2. release-please opens and maintains a **release pull request** that bumps the
   version and updates `CHANGELOG.md` from the commits since the last release.
3. Pushing more commits to `main` just updates that release PR — nothing is
   released yet.
4. When you **merge the release PR**, release-please tags the version and
   creates a GitHub Release with the changelog notes.

Only `feat:` (minor), `fix:` (patch), and breaking changes (`!` or
`BREAKING CHANGE:`, major) affect the version. `chore:`, `docs:`, `ci:`,
`test:`, and similar types do not.

## Version source

The version lives in `readwise_reader_import/__init__.py` (`__version__`) and
`.release-please-manifest.json`. Do not edit these by hand — release-please
owns them, and the Version Guard workflow fails CI if they are bumped manually.
