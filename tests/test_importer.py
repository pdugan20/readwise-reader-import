"""Unit tests for readwise_reader_import.importer."""

import io
import json
import shutil
import sys
import urllib.error
from pathlib import Path

import pytest

from readwise_reader_import import importer

# --- parse_frontmatter ---


def test_parse_frontmatter_absent():
    meta, body = importer.parse_frontmatter("just body text")
    assert meta == {}
    assert body == "just body text"


def test_parse_frontmatter_basic():
    text = "---\ntitle: Hello\nauthor: Pat\n---\nThe body."
    meta, body = importer.parse_frontmatter(text)
    assert meta == {"title": "Hello", "author": "Pat"}
    assert body == "The body."


def test_parse_frontmatter_inline_list():
    text = "---\ntags: [one, two, three]\n---\nbody"
    meta, _ = importer.parse_frontmatter(text)
    assert meta["tags"] == ["one", "two", "three"]


# --- infer_title ---


def test_infer_title_from_heading():
    title = importer.infer_title("# Real Title\n\ntext", Path("x.md"))
    assert title == "Real Title"


def test_infer_title_from_filename():
    title = importer.infer_title("no heading here", Path("my-cool_file.md"))
    assert title == "My Cool File"


# --- md_to_html ---


def test_md_to_html_basic():
    html = importer.md_to_html("# Heading\n\nA paragraph.")
    assert "<h1" in html
    assert "Heading" in html
    assert "<p>A paragraph.</p>" in html


# --- load_token ---


def test_load_token_cli_wins():
    assert importer.load_token("cli-token") == "cli-token"


def test_load_token_from_env(monkeypatch):
    monkeypatch.setenv("READWISE_TOKEN", "env-token")
    assert importer.load_token(None) == "env-token"


def test_load_token_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("READWISE_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("READWISE_TOKEN=file-token\n")
    assert importer.load_token(None) == "file-token"


def test_load_token_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("READWISE_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)
    assert importer.load_token(None) is None


# --- resolve_meta ---


def test_resolve_meta_uses_frontmatter(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text("---\ntitle: From Frontmatter\nurl: https://e.com\n---\nbody")
    meta, body = importer.resolve_meta(path, {})
    assert meta["title"] == "From Frontmatter"
    assert meta["url"] == "https://e.com"
    assert body == "body"


def test_resolve_meta_overrides_win(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text("---\ntitle: From Frontmatter\n---\nbody")
    overrides = {"title": "Override", "url": "https://e.com"}
    meta, _ = importer.resolve_meta(path, overrides)
    assert meta["title"] == "Override"


def test_resolve_meta_synthesizes_url(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text("# Title Here\n\nbody")
    meta, _ = importer.resolve_meta(path, {})
    assert meta["url"].startswith("https://local.import/")
    assert meta["category"] == "article"


def test_resolve_meta_splits_string_tags(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text("# T\n\nbody")
    overrides = {"tags": "a, b, c", "url": "https://e.com"}
    meta, _ = importer.resolve_meta(path, overrides)
    assert meta["tags"] == ["a", "b", "c"]


# --- collect_documents ---


def test_collect_documents_single_file(tmp_path):
    path = tmp_path / "one.md"
    path.write_text("# One")
    assert importer.collect_documents(path, {}) == [(path, {})]


def test_collect_documents_directory_glob(tmp_path):
    (tmp_path / "b.md").write_text("# B")
    (tmp_path / "a.md").write_text("# A")
    docs = importer.collect_documents(tmp_path, {})
    assert [p.name for p, _ in docs] == ["a.md", "b.md"]


def test_collect_documents_manifest(tmp_path):
    (tmp_path / "ch1.md").write_text("# Ch1")
    manifest = {
        "defaults": {"author": "Pat"},
        "documents": [{"file": "ch1.md", "title": "Chapter 1"}],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    docs = importer.collect_documents(tmp_path, {})
    assert len(docs) == 1
    path, meta = docs[0]
    assert path.name == "ch1.md"
    assert meta["author"] == "Pat"
    assert meta["title"] == "Chapter 1"


# --- push (dry run) ---


def test_push_dry_run(capsys):
    meta = {"url": "https://e.com", "title": "Test Doc"}
    result = importer.push("token", meta, "<p>html</p>", dry_run=True)
    assert result is True
    assert "[DRY-RUN]" in capsys.readouterr().out


# --- _update ---


def test_update_selects_only_updatable_fields(monkeypatch):
    captured = {}

    def fake_request(url, payload, token, method):
        captured.update(url=url, payload=payload, method=method)
        return object()

    monkeypatch.setattr(importer, "_request", fake_request)
    monkeypatch.setattr(importer, "_send", lambda req: (200, "{}"))
    meta = {
        "title": "T",
        "summary": "S",
        "tags": ["a"],
        "url": "https://e.com",
        "html": "<p>x</p>",
    }
    importer._update("token", "doc123", meta)
    assert captured["method"] == "PATCH"
    assert captured["url"].endswith("/doc123/")
    assert captured["payload"] == {"title": "T", "summary": "S", "tags": ["a"]}


# --- _send (rate-limit retry) ---


class _FakeResponse:
    status = 200

    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_send_retries_on_429(monkeypatch):
    calls = []

    def fake_urlopen(req):
        calls.append(req)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                "https://e.com",
                429,
                "Too Many Requests",
                {"Retry-After": "0"},
                None,
            )
        return _FakeResponse('{"ok": true}')

    monkeypatch.setattr(importer.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(importer.time, "sleep", lambda _: None)
    status, body = importer._send(object())
    assert status == 200
    assert len(calls) == 2


# --- default_output ---


def test_default_output_file(tmp_path):
    path = tmp_path / "article.md"
    path.write_text("# x")
    assert importer.default_output(path, "epub") == Path("article.epub")


def test_default_output_directory(tmp_path):
    job = tmp_path / "my-job"
    job.mkdir()
    assert importer.default_output(job, "pdf") == Path("my-job.pdf")


# --- export_file ---


def test_export_file_dry_run(tmp_path, capsys):
    (tmp_path / "a.md").write_text("# A\n\ntext")
    docs = importer.collect_documents(tmp_path, {})
    result = importer.export_file(docs, tmp_path / "out.epub", "epub", dry_run=True)
    assert result is True
    assert "[DRY-RUN]" in capsys.readouterr().out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_export_file_epub(tmp_path):
    (tmp_path / "a.md").write_text("# Chapter A\n\nText A.")
    (tmp_path / "b.md").write_text("# Chapter B\n\nText B.")
    docs = importer.collect_documents(tmp_path, {})
    output = tmp_path / "out.epub"
    importer.export_file(docs, output, "epub", dry_run=False)
    assert output.exists()
    assert output.read_bytes()[:2] == b"PK"


# --- build_parser ---


def test_build_parser_basic():
    args = importer.build_parser().parse_args(["jobs/x", "--dry-run"])
    assert args.target == "jobs/x"
    assert args.dry_run is True
    assert args.export == "reader"


def test_build_parser_export_option():
    args = importer.build_parser().parse_args(
        ["jobs/x", "--export", "epub", "--output", "book.epub"]
    )
    assert args.export == "epub"
    assert args.output == "book.epub"


def test_build_parser_version_flag():
    with pytest.raises(SystemExit):
        importer.build_parser().parse_args(["--version"])


# --- parse_frontmatter edge cases ---


def test_parse_frontmatter_unclosed():
    text = "---\ntitle: X\nno closing fence"
    meta, body = importer.parse_frontmatter(text)
    assert meta == {}
    assert body == text


def test_parse_frontmatter_skips_blank_and_comment():
    meta, _ = importer.parse_frontmatter("---\n# a comment\n\ntitle: Real\n---\nbody")
    assert meta == {"title": "Real"}


# --- _request ---


def test_request_builds_post():
    req = importer._request("https://e.com/x", {"a": 1}, "tok", "POST")
    assert req.method == "POST"
    assert req.full_url == "https://e.com/x"
    assert req.get_header("Authorization") == "Token tok"
    assert json.loads(req.data) == {"a": 1}


# --- push (live paths, mocked transport) ---


def test_push_creates(monkeypatch, capsys):
    monkeypatch.setattr(importer, "_send", lambda req: (201, '{"id": "x", "url": "u"}'))
    meta = {"url": "https://e.com", "title": "New Doc"}
    assert importer.push("tok", meta, "<p>h</p>", dry_run=False) is True
    assert "created" in capsys.readouterr().out


def test_push_updates_existing(monkeypatch, capsys):
    monkeypatch.setattr(
        importer, "_send", lambda req: (200, '{"id": "abc", "url": "u"}')
    )
    meta = {"url": "https://e.com", "title": "Old Doc", "summary": "s"}
    assert importer.push("tok", meta, "<p>h</p>", dry_run=False) is True
    assert "updated" in capsys.readouterr().out


def test_push_handles_http_error(monkeypatch, capsys):
    def boom(req):
        raise urllib.error.HTTPError(
            "https://e.com", 400, "Bad Request", {}, io.BytesIO(b"nope")
        )

    monkeypatch.setattr(importer, "_send", boom)
    meta = {"url": "https://e.com", "title": "Doc"}
    assert importer.push("tok", meta, "<p>h</p>", dry_run=False) is False
    assert "[ERROR]" in capsys.readouterr().out


# --- export_reader ---


def test_export_reader(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_text("# A\n\ntext")
    monkeypatch.setattr(importer, "push", lambda *a, **k: True)
    docs = importer.collect_documents(tmp_path, {})
    assert importer.export_reader(docs, "tok", dry_run=False, save_html=False)


# --- export_file error handling ---


def test_export_file_requires_pandoc(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_text("# A\n\ntext")
    monkeypatch.setattr(importer.shutil, "which", lambda _: None)
    docs = importer.collect_documents(tmp_path, {})
    with pytest.raises(SystemExit):
        importer.export_file(docs, tmp_path / "o.epub", "epub", dry_run=False)


# --- main ---


def test_main_target_not_found(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["reader-import", "no/such/path"])
    with pytest.raises(SystemExit):
        importer.main()


def test_main_reader_dry_run(tmp_path, monkeypatch, capsys):
    (tmp_path / "a.md").write_text("# A\n\ntext")
    monkeypatch.setattr(sys, "argv", ["reader-import", str(tmp_path), "--dry-run"])
    importer.main()
    assert "converted: 1/1" in capsys.readouterr().out


def test_main_epub_dry_run(tmp_path, monkeypatch, capsys):
    (tmp_path / "a.md").write_text("# A\n\ntext")
    monkeypatch.setattr(
        sys,
        "argv",
        ["reader-import", str(tmp_path), "--export", "epub", "--dry-run"],
    )
    importer.main()
    assert "[DRY-RUN]" in capsys.readouterr().out
