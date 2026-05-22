# readwise-reader-import

[![CI](https://github.com/pdugan20/readwise-reader-import/actions/workflows/ci.yml/badge.svg)](https://github.com/pdugan20/readwise-reader-import/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/pdugan20/readwise-reader-import?logo=github)](https://github.com/pdugan20/readwise-reader-import/releases)
[![Python](https://img.shields.io/badge/Python-%3E%3D3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?logo=opensourceinitiative&logoColor=white)](https://opensource.org/licenses/MIT)

Turn markdown into clean, individually highlightable articles in Readwise Reader. Built for long-form content where Reader's own parser struggles with cluttered source pages — multi-chapter reports, gated markdown exports, anything you would rather hand-clean than scrape.

It converts markdown to clean HTML and pushes each document to the Readwise Reader API as its own article, with a real source URL, summary, cover image, and tags. Zero runtime dependencies — just the Python standard library, plus `pandoc` or the `markdown` package for conversion.

## Install

```bash
pipx install git+https://github.com/pdugan20/readwise-reader-import.git
```

This installs the `reader-import` command. Conversion needs either `pandoc`
(`brew install pandoc`) or the `markdown` Python package — one is enough.

## Setup

Get a Readwise token at <https://readwise.io/access_token>, then either export
it or drop it in a `.env` file in the directory you run from:

```bash
export READWISE_TOKEN=your_token_here
# or
echo 'READWISE_TOKEN=your_token_here' > .env
```

## Usage

A **job** is a folder holding markdown files plus a `manifest.json` mapping each
file to its title and source URL. Run the job and every file becomes its own
Reader article.

```bash
reader-import jobs/my-job --dry-run   # convert and report, no API calls
reader-import jobs/my-job             # push for real
```

`--dry-run` is always worth doing first.

### Manifest format

```json
{
  "defaults": {
    "author": "Example Author",
    "category": "article",
    "location": "new",
    "tags": ["example"]
  },
  "documents": [
    {
      "file": "chapter-one.md",
      "title": "Chapter One",
      "url": "https://example.com/chapter-one",
      "summary": "A one-line summary shown in the Reader list.",
      "image_url": "https://example.com/cover.png"
    }
  ]
}
```

`defaults` apply to every document; per-document keys override them.

### Other ways to call it

```bash
# A single file, metadata passed inline
reader-import article.md --title 'My Article' --url https://example.com

# Every .md in a directory (metadata from each file's frontmatter)
reader-import ./some-folder --tags research
```

Single files can also carry flat YAML frontmatter (`title`, `author`, `url`,
`tags`, `category`, `location`, `summary`). Precedence: CLI flags / manifest
entry, then frontmatter, then inferred.

## How it works

- Markdown is converted to clean HTML and sent to the Readwise Reader save
  endpoint as a native article — Reader's strongest highlighting surface.
- Each article keeps its real source URL as the canonical link; that URL is
  also the de-duplication key.
- `summary` and `image_url` must be set at creation time — the save endpoint
  does not update them on a URL that already exists.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, testing, commit
conventions, and how releases work.
