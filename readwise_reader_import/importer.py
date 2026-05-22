"""Import markdown documents into Readwise Reader, or export them as files.

Usage:
  reader-import JOB_DIR            push every document a manifest.json lists
  reader-import FILE.md [opts]     push a single markdown file
  reader-import DIR     [opts]     push every *.md in a directory

Export targets (--export):
  reader   push to Readwise Reader via the API (default)
  epub     combine the documents into a single EPUB file (needs pandoc)
  pdf      combine the documents into a single PDF file (needs pandoc)

Common options:
  --dry-run         convert and report, but write nothing
  --export TARGET   reader | epub | pdf  (default: reader)
  --output PATH     output file for epub / pdf export
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
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from readwise_reader_import import __version__

SAVE_URL = "https://readwise.io/api/v3/save/"
UPDATE_URL = "https://readwise.io/api/v3/update/"
MAX_RETRIES = 4

# Scalar metadata fields the Reader update endpoint can refresh.
UPDATABLE_FIELDS = ("title", "author", "summary", "image_url", "location", "category")


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


def _request(url, payload, token, method):
    """Build a JSON request for the Readwise Reader API."""
    return urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )


def _send(req):
    """Send an API request, retrying on HTTP 429 with backoff.

    Returns (status_code, response_body_text).
    """
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < MAX_RETRIES - 1:
                wait = int(exc.headers.get("Retry-After") or 2**attempt)
                print(f"  [INFO]    rate limited; retrying in {wait}s")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("retry loop exhausted")


def _update(token, doc_id, meta):
    """Refresh an existing Reader document's metadata via the update endpoint."""
    fields = {k: meta[k] for k in UPDATABLE_FIELDS if meta.get(k)}
    if meta.get("tags"):
        fields["tags"] = meta["tags"]
    if not fields:
        return
    try:
        _send(_request(f"{UPDATE_URL}{doc_id}/", fields, token, "PATCH"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        print(f"  [ERROR]   update failed: {exc.code} {detail}")


def push(token, meta, html, dry_run):
    """Push one document to Readwise Reader, refreshing it if it already exists."""
    title = meta["title"]
    if dry_run:
        print(f"  [DRY-RUN] {title}  ({len(html):,} chars HTML)")
        return True

    payload = {
        "url": meta["url"],
        "html": html,
        "title": title,
        "should_clean_html": False,
        "saved_using": "readwise-reader-import",
    }
    for key in ("author", "category", "location", "summary", "image_url"):
        if meta.get(key):
            payload[key] = meta[key]
    if meta.get("tags"):
        payload["tags"] = meta["tags"]

    try:
        status, body_text = _send(_request(SAVE_URL, payload, token, "POST"))
    except urllib.error.HTTPError as exc:
        print(f"  [ERROR]   {title}: {exc.code} {exc.read().decode('utf-8')}")
        return False

    doc = json.loads(body_text)
    if status == 200:
        # The document already existed; the save endpoint does not refresh
        # metadata, so update it explicitly.
        _update(token, doc["id"], meta)
        print(f"  [SUCCESS] updated  {title}")
    else:
        print(f"  [SUCCESS] created  {title}")
    print(f"            {doc.get('url', '')}")
    return True


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


def default_output(target, fmt):
    """Derive a default epub / pdf output filename from the import target."""
    stem = target.stem if target.is_file() else target.name
    return Path(f"{stem}.{fmt}")


def export_reader(documents, token, dry_run, save_html):
    """Convert and push every document to Readwise Reader."""
    pushed = 0
    for path, overrides in documents:
        if not path.exists():
            print(f"  [SKIP]    {path} not found")
            continue
        meta, body = resolve_meta(path, overrides)
        html = md_to_html(body)
        if save_html:
            path.with_suffix(".html").write_text(html, encoding="utf-8")
        if push(token, meta, html, dry_run):
            pushed += 1
    verb = "converted" if dry_run else "imported"
    print(f"\n{verb}: {pushed}/{len(documents)} document(s).")
    return pushed == len(documents)


def export_file(documents, output, fmt, dry_run):
    """Combine documents into a single EPUB or PDF file via pandoc."""
    parts, title, author = [], None, None
    for path, overrides in documents:
        if not path.exists():
            print(f"  [SKIP]    {path} not found")
            continue
        front, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        meta = {**front, **{k: v for k, v in overrides.items() if v}}
        title = title or meta.get("title") or infer_title(body, path)
        author = author or meta.get("author")
        parts.append(body)

    if not parts:
        sys.exit("No documents to export.")
    if dry_run:
        print(f"  [DRY-RUN] would write {output} from {len(parts)} document(s)")
        return True
    if shutil.which("pandoc") is None:
        sys.exit(f"{fmt.upper()} export needs pandoc — install it: brew install pandoc")

    cmd = ["pandoc", "-f", "gfm", "-o", str(output)]
    if title:
        cmd += ["--metadata", f"title={title}"]
    if author:
        cmd += ["--metadata", f"author={author}"]
    try:
        subprocess.run(
            cmd,
            input="\n\n".join(parts),
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        sys.exit(f"{fmt.upper()} export failed: {exc.stderr.strip()}")
    print(f"  [SUCCESS] wrote {output} from {len(parts)} document(s)")
    return True


def build_parser():
    """Construct the argparse command-line parser."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("target", help="a job dir, a directory of .md, or one .md file")
    parser.add_argument(
        "--export",
        choices=["reader", "epub", "pdf"],
        default="reader",
        help="export target (default: reader)",
    )
    parser.add_argument("--output", help="output file for epub / pdf export")
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
    """Convert markdown documents and import or export them."""
    args = build_parser().parse_args()

    target = Path(args.target)
    if not target.exists():
        sys.exit(f"Not found: {target}")

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

    if args.export == "reader":
        token = None if args.dry_run else load_token(args.token)
        if not args.dry_run and not token:
            sys.exit(
                "No Readwise token. Pass --token, set READWISE_TOKEN, or add "
                "it to a .env file.\nGet one at https://readwise.io/access_token"
            )
        success = export_reader(documents, token, args.dry_run, args.save_html)
    else:
        output = (
            Path(args.output) if args.output else default_output(target, args.export)
        )
        success = export_file(documents, output, args.export, args.dry_run)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
