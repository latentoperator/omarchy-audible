"""B5 — ``local`` and ``remove``: the filesystem scan and removal safety.

``remove`` deletes exactly ``<booksDir>/<asin>/`` (ARCHITECTURE 4.4). It refuses
a path that escapes ``booksDir`` and refuses a symlink, and it makes no network
call of any kind.
"""

from __future__ import annotations

import http.client
import json
import socket
import urllib.request
from pathlib import Path

ASIN = "B00FAKE01"


def _make_book(paths, asin: str, *, payload: bytes = b"x" * 100, downloaded_at: str = "2026-01-02T03:04:05Z") -> Path:
    directory = paths.books_dir / asin
    directory.mkdir(parents=True)
    (directory / "book.m4b").write_bytes(payload)
    (directory / "meta.json").write_text(
        json.dumps({"asin": asin, "downloaded_at": downloaded_at}), encoding="utf-8"
    )
    return directory


def test_local_lists_only_downloaded_books(run_cli, validate_stream, paths):
    _make_book(paths, "B00FAKE01", payload=b"a" * 100)
    _make_book(paths, "B00FAKE02", payload=b"b" * 250)
    (paths.books_dir / "B00EMPTY").mkdir()
    (paths.books_dir / "B00PARTIAL").mkdir()
    (paths.books_dir / "B00PARTIAL" / ".partial").mkdir()

    result = run_cli("local", fake=True)
    assert result.returncode == 0, result.stderr
    parsed = validate_stream(result, expect_last="done")
    local = next(event for event in parsed if event["type"] == "local")

    assert [book["asin"] for book in local["books"]] == ["B00FAKE01", "B00FAKE02"]
    first = local["books"][0]
    assert first["downloaded_at"] == "2026-01-02T03:04:05Z"
    assert first["size"] >= 100
    assert local["books"][1]["size"] >= 250


def test_local_falls_back_to_the_file_mtime_without_meta(run_cli, validate_stream, paths):
    directory = paths.books_dir / "B00FAKE07"
    directory.mkdir()
    (directory / "book.m4b").write_bytes(b"z" * 10)

    parsed = validate_stream(run_cli("local", fake=True), expect_last="done")
    local = next(event for event in parsed if event["type"] == "local")
    assert [book["asin"] for book in local["books"]] == ["B00FAKE07"]
    assert local["books"][0]["downloaded_at"]


def test_remove_deletes_one_book_and_reports_freed_bytes(
    run_cli, validate_stream, paths
):
    target = _make_book(paths, "B00FAKE01", payload=b"c" * 512)
    other = _make_book(paths, "B00FAKE02", payload=b"d" * 32)

    result = run_cli("remove", "B00FAKE01", fake=True)
    assert result.returncode == 0, result.stderr
    parsed = validate_stream(result, expect_last="done")
    assert parsed[-1]["freed_bytes"] >= 512
    assert not target.exists()
    assert other.is_dir()


def test_remove_refuses_a_path_outside_books_dir(run_cli, events, paths, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")

    result = run_cli("remove", "../outside", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "unsafe_path"
    assert (outside / "keep.txt").is_file()


def test_remove_refuses_a_symlink_inside_books_dir(run_cli, events, paths):
    real = _make_book(paths, "B00FAKE03")
    link = paths.books_dir / "B00FAKE04"
    link.symlink_to(real)

    result = run_cli("remove", "B00FAKE04", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "unsafe_path"
    assert link.is_symlink()
    assert real.is_dir()


def test_remove_refuses_a_symlink_pointing_outside(run_cli, events, paths, tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep", encoding="utf-8")
    link = paths.books_dir / "B00LINK01"
    link.symlink_to(victim)

    result = run_cli("remove", "B00LINK01", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "unsafe_path"
    assert (victim / "keep.txt").is_file()


def test_remove_refuses_a_book_that_is_not_local(run_cli, events, paths):
    result = run_cli("remove", "B00NOPE01", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "not_local"


def test_remove_makes_no_network_call(env, monkeypatch, capsys, paths):
    """Run ``remove`` in-process with every socket entry point blocked."""
    target = _make_book(paths, ASIN)

    def blocked(*_args, **_kwargs):
        raise AssertionError("remove attempted a network call")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", blocked)
    for key in (
        "HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_RUNTIME_DIR",
        "OMARCHY_AUDIBLE_BOOKS_DIR",
    ):
        monkeypatch.setenv(key, env[key])
    monkeypatch.delenv("OMARCHY_AUDIBLE_FAKE", raising=False)

    from omarchy_audible.cli import main

    code = main(["remove", ASIN, "--fake"])
    assert code == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert events[-1]["type"] == "done"
    assert not target.exists()
