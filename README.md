# readwise-reader-import

[![CI](https://github.com/pdugan20/readwise-reader-import/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/pdugan20/readwise-reader-import/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/pdugan20/readwise-reader-import/graph/badge.svg?token=TMRZFIrp1E)](https://codecov.io/gh/pdugan20/readwise-reader-import)
[![Release](https://img.shields.io/github/v/release/pdugan20/readwise-reader-import)](https://github.com/pdugan20/readwise-reader-import/releases/latest)
[![License](https://img.shields.io/github/license/pdugan20/readwise-reader-import)](LICENSE)

Turn markdown into clean, individually highlightable articles in Readwise Reader — or export it as EPUB or PDF. Built for long-form content where Reader's own parser struggles with cluttered source pages: multi-chapter reports, gated markdown exports, anything you would rather hand-clean than scrape.

Zero runtime dependencies — just the Python standard library, plus `pandoc` or the `markdown` package for conversion.

## Install

```bash
pipx install git+https://github.com/pdugan20/readwise-reader-import.git
```

Installs the `reader-import` command. Conversion needs `pandoc`
(`brew install pandoc`) or the `markdown` Python package.

## Setup

Get a Readwise token at <https://readwise.io/access_token>, then export it or
drop it in a `.env` file in the directory you run from:

```bash
echo 'READWISE_TOKEN=your_token_here' > .env
```

## Usage

A **job** is a folder of markdown files plus a `manifest.json` mapping each file
to its title and source URL. Run the job and every file becomes its own Reader
article.

```bash
reader-import jobs/my-job --dry-run   # convert and report, no API calls
reader-import jobs/my-job             # push for real
```

Re-running refreshes existing articles, matched by source URL. You can also
point it at a single `.md` file or a plain directory, and pass metadata with
`--title` / `--url` / `--tags` or via YAML frontmatter.

### Manifest format

```json
{
  "defaults": { "author": "Example Author", "tags": ["example"] },
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

### Export to EPUB or PDF

Instead of pushing to Reader, combine a job into a single file — each document
becomes a chapter:

```bash
reader-import jobs/my-job --export epub
reader-import jobs/my-job --export pdf --output report.pdf
```

PDF export needs a pandoc PDF engine installed.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, testing, commit
conventions, and how releases work.
