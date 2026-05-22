# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Overview

`readwise-reader-import` is a zero-dependency Python CLI that converts markdown
into clean HTML and pushes it to the Readwise Reader API as individual
articles. The command is `reader-import`.

## Structure

- `readwise_reader_import/importer.py` — all CLI logic (arg parsing,
  markdown conversion, metadata resolution, Reader API calls)
- `readwise_reader_import/__init__.py` — holds `__version__`
- `tests/` — pytest unit tests
- `jobs/` — example import jobs; each is a folder with a `manifest.json`
  plus markdown files (the markdown is gitignored as third-party content)

## Conventions

- Runtime code stays standard-library only. `markdown` and `pandoc` are
  optional converters, not runtime dependencies.
- Lint and format with Ruff: `make lint` / `make format`.
- Tests run with `make test`.
- Commits follow Conventional Commits — see [CONTRIBUTING.md](CONTRIBUTING.md).
- The version is owned by release-please. Never edit `__version__` or
  `.release-please-manifest.json` by hand; see [docs/releasing.md](docs/releasing.md).

## Reader API notes

- The save endpoint de-duplicates on `url`; re-posting an existing URL does
  not update `summary` or `image_url` — those must be set at creation time.
