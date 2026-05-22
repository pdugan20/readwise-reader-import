# Contributing

## Setup

```bash
git clone https://github.com/pdugan20/readwise-reader-import.git
cd readwise-reader-import
make dev
```

`make dev` installs the package with dev dependencies and sets up the
pre-commit hooks (formatting, linting, and commit-message checks).

## Running tests

```bash
make test
```

Tests run with coverage reporting.

## Linting and formatting

```bash
make lint     # check only (Ruff lint + format)
make format   # auto-fix
make check    # lint + test
```

## Commit messages

This project uses [Conventional Commits](https://www.conventionalcommits.org/).
Commitlint enforces the format via a pre-commit hook, and release-please uses
it to determine version bumps.

### Format

```text
<type>: <description>
```

### Types

- **feat** — new feature (triggers a minor release)
- **fix** — bug fix (triggers a patch release)
- **docs** — documentation changes
- **chore** — maintenance, dependencies, tooling
- **refactor** — code changes that neither add features nor fix bugs
- **test** — adding or updating tests
- **ci** — CI and workflow changes

### Rules

- Use lowercase for the subject line
- Keep the header under 100 characters
- No period at the end of the subject

## Releasing

Releases are automated with release-please. See [docs/releasing.md](docs/releasing.md)
for how versioning and releases work.
