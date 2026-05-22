"""Import markdown documents into Readwise Reader as clean, highlightable
articles.

Usage:
  reader-import JOB_DIR          push every document a manifest.json lists
  reader-import FILE.md [opts]   push a single markdown file
  reader-import DIR     [opts]   push every *.md in a directory

Common options:
  --dry-run         convert and report, but make no API calls
  --save-html       also write the converted .html next to each source file
  --title  TEXT     metadata overrides (single-file / DIR mode)
  --author TEXT
  --url    URL      canonical source link; also the de-duplication key
  --tags   a,b,c
  --category CAT    article|email|rss|highlight|note|pdf|epub|tweet|video
  --location LOC    new|later|shortlist|archive|feed
  --token  TOKEN    Readwise token (else READWISE_TOKEN env, else .env file)

Metadata precedence: CLI flags / manifest entry > YAML frontmatter > inferred.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from readwise_reader_import import __version__

API_URL = "https://readwise.io/api/v3/save/"


def load_token(cli_token):
    """Resolve the Readwise token: CLI flag, env var, then a local .env file."""
    if cli_token:
        return cli_token
    if os.environ.get("READWISE_TOKEN"):
        return os.environ["READWISE_TOKEN"]
    env_file = Path(".env")
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("READWISE_TOKEN=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip("'\"")
    return None


def parse_frontmatter(text):
    """Split flat YAML frontmatter from a markdown body.

    Returns (metadata_dict, body). Supports `key: value` and inline lists
    written as `[a, b]`. No nested structures.
    """
    if not text.startswith("---"):
        return {}, text
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not match:
        return {}, text
    meta = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if value.startswith("[") and value.endswith("]"):
            value = [
                v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()
            ]
        meta[key] = value
    return meta, match.group(2)


def infer_title(body, path):
    """Use the first H1 heading as the title, else the prettified filename."""
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").replace("_", " ").title()


def md_to_html(md_body):
    """Convert markdown to HTML, preferring `markdown`, then pandoc."""
    try:
        import markdown

        return markdown.markdown(
            md_body, extensions=["extra", "sane_lists", "smarty", "toc"]
        )
    except ImportError:
        pass
    try:
        return subprocess.run(
            ["pandoc", "-f", "gfm", "-t", "html"],
            input=md_body,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        sys.exit(
            f"Could not convert markdown ({exc}).\n"
            "Install a converter:  pip install markdown   (or)   brew install pandoc"
        )


def push(token, meta, html, dry_run):
    """Send one document to the Readwise Reader save endpoint."""
    payload = {
        "url": meta["url"],
        "html": html,
        "title": meta["title"],
        "should_clean_html": False,
        "saved_using": "readwise-reader-import",
    }
    for key in ("author", "category", "location", "summary", "image_url"):
        if meta.get(key):
            payload[key] = meta[key]
    if meta.get("tags"):
        payload["tags"] = meta["tags"]

    if dry_run:
        print(f"  [DRY-RUN] {meta['title']}  ({len(html):,} chars HTML)")
        return True

    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        print(f"  [SUCCESS] {meta['title']}")
        print(f"            {body.get('url', '')}")
        return True
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        print(f"  [ERROR]   {meta['title']}: {exc.code} {detail}")
        return False


def resolve_meta(path, overrides):
    """Build a document's metadata from frontmatter, overrides, and fallbacks."""
    raw = path.read_text(encoding="utf-8")
    front, body = parse_frontmatter(raw)

    meta = {}
    meta.update(front)
    meta.update({k: v for k, v in overrides.items() if v})

    if not meta.get("title"):
        meta["title"] = infer_title(body, path)
    if not meta.get("url"):
        digest = hashlib.sha1(path.name.encode()).hexdigest()[:10]
        meta["url"] = f"https://local.import/{path.stem}-{digest}"
        print(f"  [INFO]    no source url for {path.name}; using {meta['url']}")
    if isinstance(meta.get("tags"), str):
        meta["tags"] = [t.strip() for t in meta["tags"].split(",") if t.strip()]
    meta.setdefault("category", "article")

    return meta, body


def collect_documents(target, overrides):
    """Yield (path, overrides) pairs for every document to import."""
    if target.is_file():
        return [(target, overrides)]

    manifest = target / "manifest.json"
    if manifest.exists():
        spec = json.loads(manifest.read_text(encoding="utf-8"))
        defaults = spec.get("defaults", {})
        docs = []
        for entry in spec.get("documents", []):
            path = target / entry["file"]
            merged = {
                **defaults,
                **{k: v for k, v in entry.items() if k != "file"},
            }
            merged.update({k: v for k, v in overrides.items() if v})
            docs.append((path, merged))
        return docs

    return [(p, overrides) for p in sorted(target.glob("*.md"))]


def build_parser():
    """Construct the argparse command-line parser."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("target", help="a job dir, a directory of .md, or one .md file")
    parser.add_argument("--token")
    parser.add_argument("--title")
    parser.add_argument("--author")
    parser.add_argument("--url")
    parser.add_argument("--summary")
    parser.add_argument("--tags")
    parser.add_argument("--category")
    parser.add_argument("--location")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--save-html", action="store_true")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def main():
    """Convert markdown documents and push them to Readwise Reader."""
    args = build_parser().parse_args()

    target = Path(args.target)
    if not target.exists():
        sys.exit(f"Not found: {target}")

    token = None if args.dry_run else load_token(args.token)
    if not args.dry_run and not token:
        sys.exit(
            "No Readwise token. Pass --token, set READWISE_TOKEN, or add it "
            "to a .env file.\nGet one at https://readwise.io/access_token"
        )

    overrides = {
        "title": args.title,
        "author": args.author,
        "url": args.url,
        "summary": args.summary,
        "tags": args.tags,
        "category": args.category,
        "location": args.location,
    }

    documents = collect_documents(target, overrides)
    if not documents:
        sys.exit(f"No markdown documents found under {target}")

    ok = 0
    for path, doc_overrides in documents:
        if not path.exists():
            print(f"  [SKIP]    {path} not found")
            continue
        meta, body = resolve_meta(path, doc_overrides)
        html = md_to_html(body)
        if args.save_html:
            path.with_suffix(".html").write_text(html, encoding="utf-8")
        if push(token, meta, html, args.dry_run):
            ok += 1

    verb = "converted" if args.dry_run else "imported"
    print(f"\n{verb}: {ok}/{len(documents)} document(s).")
    if ok < len(documents):
        sys.exit(1)


if __name__ == "__main__":
    main()
