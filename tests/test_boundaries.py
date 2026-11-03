"""Synthetic job/API boundaries; no Reader requests or real documents."""

import http.client
import io
import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from readwise_reader_import import importer


class Response(io.BytesIO):
    status = 201


def manifest(root, files):
    (root / "manifest.json").write_text(
        json.dumps({"documents": [{"file": name} for name in files]})
    )


@pytest.mark.parametrize(
    "name", ["../outside.md", "/tmp/outside.md", "", None, 42, "."]
)
def test_manifest_rejects_unsafe_inputs_before_import(tmp_path, name):
    manifest(tmp_path, [name])
    with pytest.raises(ValueError):
        importer.collect_documents(tmp_path, {})


def test_symlink_escape_and_glob_escape_are_rejected(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("synthetic outside content")
    (job / "linked.md").symlink_to(outside)
    with pytest.raises(ValueError):
        importer.collect_documents(job, {})
    manifest(job, ["linked.md"])
    with pytest.raises(ValueError):
        importer.collect_documents(job, {})


def test_manifest_itself_cannot_escape_root(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text('{"documents":[]}')
    (job / "manifest.json").symlink_to(outside)
    with pytest.raises(ValueError):
        importer.collect_documents(job, {})


def test_contained_nested_inputs_and_symlink_aliases_keep_identity(tmp_path):
    folder = tmp_path / "nested"
    folder.mkdir()
    source = folder / "source.md"
    source.write_text("# Test")
    alias = tmp_path / "alias.md"
    alias.symlink_to(source)
    manifest(tmp_path, ["nested/source.md", "alias.md", "missing.md"])
    docs = importer.collect_documents(tmp_path, {})
    assert [p for p, _ in docs] == [source, alias, tmp_path / "missing.md"]
    assert importer.collect_documents(source, {}) == [(source, {})]


@pytest.mark.parametrize(
    "spec", [[], {"defaults": []}, {"documents": {}}, {"documents": [42]}]
)
def test_malformed_manifest_is_rejected(tmp_path, spec):
    (tmp_path / "manifest.json").write_text(json.dumps(spec))
    with pytest.raises(ValueError):
        importer.collect_documents(tmp_path, {})


def test_cli_rejects_entire_job_before_any_network(monkeypatch, tmp_path):
    (tmp_path / "valid.md").write_text("# Test")
    manifest(tmp_path, ["valid.md", "../outside.md"])
    monkeypatch.setattr("sys.argv", ["reader-import", str(tmp_path)])
    monkeypatch.setattr(
        importer, "export_reader", lambda *args: pytest.fail("must not import")
    )
    with pytest.raises(SystemExit, match="Invalid job input"):
        importer.main()


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, 2),
        ("bad", 2),
        ("-10", 2),
        ("9999999999999", 60),
        ("0", 0),
        ("3", 3),
        ("Fri, 31 Dec 2099 23:59:59 GMT", 60),
        ("Mon, 01 Jan 1990 00:00:00 GMT", 0),
    ],
)
def test_retry_after_is_bounded(value, expected):
    assert importer._retry_wait(value, 1) == expected


def test_request_timeout_and_response_byte_cap(monkeypatch):
    calls = []

    def open_request(req, timeout):
        calls.append(timeout)
        return Response(b"x" * (importer.MAX_API_RESPONSE_BYTES + 1))

    monkeypatch.setattr(importer._API_OPENER, "open", open_request)
    with pytest.raises(ValueError, match="size limit"):
        importer._send(object())
    assert calls == [importer.REQUEST_TIMEOUT_SECONDS]


def test_retry_count_is_finite_and_errors_closed(monkeypatch):
    calls, waits, bodies = [], [], []

    def open_request(req, timeout):
        calls.append(timeout)
        body = io.BytesIO(b"synthetic private error body")
        bodies.append(body)
        raise urllib.error.HTTPError(
            "https://example.invalid/",
            429,
            "rate limited",
            {"Retry-After": "999999"},
            body,
        )

    monkeypatch.setattr(importer._API_OPENER, "open", open_request)
    monkeypatch.setattr(importer.time, "sleep", waits.append)
    with pytest.raises(urllib.error.HTTPError) as error:
        importer._send(object())
    error.value.close()
    assert len(calls) == importer.MAX_RETRIES
    assert waits == [importer.MAX_RETRY_WAIT_SECONDS] * (importer.MAX_RETRIES - 1)
    assert all(body.closed for body in bodies)


def test_api_failures_do_not_print_response_body_or_exception_secrets(
    monkeypatch, capsys
):
    def timeout(*args, **kwargs):
        raise TimeoutError("synthetic-secret")

    monkeypatch.setattr(importer._API_OPENER, "open", timeout)
    assert not importer.push(
        "fake-token",
        {"title": "Test", "url": "https://example.invalid/test"},
        "test",
        False,
    )
    importer._update("fake-token", "id", {"title": "Test"})
    assert "synthetic-secret" not in capsys.readouterr().out

    def http_error(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://example.invalid/",
            500,
            "error",
            {},
            io.BytesIO(b"synthetic-secret"),
        )

    monkeypatch.setattr(importer._API_OPENER, "open", http_error)
    assert not importer.push(
        "fake-token",
        {"title": "Test", "url": "https://example.invalid/test"},
        "test",
        False,
    )
    importer._update("fake-token", "id", {"title": "Test"})
    assert "synthetic-secret" not in capsys.readouterr().out


def test_api_redirect_does_not_forward_token_to_another_route():
    visited = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            visited.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/untrusted")
            self.end_headers()

        def do_GET(self):  # noqa: N802
            visited.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = importer._request(
            f"http://127.0.0.1:{server.server_port}/save", {}, "fake-token", "POST"
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            importer._send(request)
        error.value.close()
        assert visited == ["/save"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_dry_run_save_html_writes_nothing(monkeypatch, tmp_path):
    source = tmp_path / "article.md"
    source.write_text("# Test")
    monkeypatch.setattr(importer, "md_to_html", lambda _: "<p>synthetic</p>")
    monkeypatch.setattr(
        importer, "_send", lambda *args: pytest.fail("must not request")
    )
    assert importer.export_reader([(source, {})], None, True, True)
    assert not source.with_suffix(".html").exists()


def test_html_replacement_does_not_follow_symlinks_and_survives_failure(
    monkeypatch, tmp_path
):
    outside = tmp_path / "outside.txt"
    outside.write_text("original")
    output = tmp_path / "article.html"
    output.symlink_to(outside)
    importer._write_html(output, "new html")
    assert outside.read_text() == "original"
    assert output.read_text() == "new html"
    assert not output.is_symlink()

    def fail_replace(*args):
        raise OSError("synthetic replacement failure")

    monkeypatch.setattr(importer.os, "replace", fail_replace)
    before = set(tmp_path.iterdir())
    with pytest.raises(OSError):
        importer._write_html(output, "replacement")
    assert output.read_text() == "new html"
    assert set(tmp_path.iterdir()) == before


def test_parent_symlink_cannot_send_adjacent_html_outside_job(tmp_path):
    root = tmp_path / "job"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    source = root / "source.md"
    source.write_text("# Synthetic")
    (root / "nested").symlink_to(outside, target_is_directory=True)
    (outside / "alias.md").symlink_to(source)
    (outside / "alias.html").write_text("must survive")
    manifest(root, ["nested/alias.md"])
    with pytest.raises(ValueError):
        importer.collect_documents(root, {})
    assert (outside / "alias.html").read_text() == "must survive"


def test_dangling_manifest_does_not_fall_back_to_glob(tmp_path):
    (tmp_path / "unlisted.md").write_text("# Synthetic")
    (tmp_path / "manifest.json").symlink_to(tmp_path.parent / "missing-manifest.json")
    with pytest.raises(ValueError):
        importer.collect_documents(tmp_path, {})


@pytest.mark.parametrize(
    "error",
    [
        http.client.BadStatusLine("synthetic-secret"),
        http.client.IncompleteRead(b"synthetic-secret", 100),
    ],
)
def test_protocol_failures_are_sanitized(monkeypatch, capsys, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(importer._API_OPENER, "open", fail)
    assert not importer.push(
        "fake-token", {"title": "Test", "url": "https://example.invalid"}, "test", False
    )
    assert not importer._update("fake-token", "id", {"title": "Test"})
    assert "synthetic-secret" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "status, body",
    [
        (201, "invalid-json"),
        (200, "[]"),
        (200, "{}"),
        (201, '{"id":true}'),
        (200, '{"id":"../../wrong"}'),
        (201, '{"id":"ok","url":[]}'),
        (202, '{"id":"ok"}'),
    ],
)
def test_invalid_success_does_not_raise_or_update(monkeypatch, capsys, status, body):
    monkeypatch.setattr(importer, "_send", lambda request: (status, body))
    monkeypatch.setattr(
        importer, "_update", lambda *args: pytest.fail("must not update")
    )
    assert not importer.push(
        "fake-token", {"title": "Test", "url": "https://example.invalid"}, "test", False
    )
    assert "[SUCCESS]" not in capsys.readouterr().out


def test_update_failure_is_not_reported_as_success(monkeypatch, capsys):
    responses = iter([(200, '{"id":"id"}'), (200, '{"id":"wrong"}')])
    monkeypatch.setattr(importer, "_send", lambda request: next(responses))
    assert not importer.push(
        "fake-token", {"title": "Test", "url": "https://example.invalid"}, "test", False
    )
    assert "[SUCCESS]" not in capsys.readouterr().out
    assert importer._update("fake-token", "id", {}) is True
