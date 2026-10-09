"""R1b safe books paths, location record, and notice text."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import qjs
from omarchy_audible import commands
from omarchy_audible.paths import Paths, books_dir_problem, requested_books_dir


def _seed_book(root: Path, asin: str = "B00FAKE01") -> None:
    book = root / asin
    book.mkdir(parents=True)
    (book / "book.m4b").write_bytes(b"fake")


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "~/Audiobooks/Audible"),
        ("   ", "~/Audiobooks/Audible"),
        ("~/Books", "~/Books"),
        ("~", "~"),
        ("~someone/Books", "~someone/Books"),
        ("/$HOME/Books", "/$HOME/Books"),
        ("relative", "relative"),
    ],
)
def test_requested_books_dir_parses_only_supported_tilde_forms(
    tmp_path, value, expected
):
    home = tmp_path / "home"
    path = requested_books_dir(value, home)
    assert str(path).replace(str(home), "~") == expected


def test_books_dir_path_rules_and_symlinks(tmp_path):
    home = tmp_path / "home"
    config, data, runtime = (tmp_path / name for name in ("config", "data", "runtime"))
    paths = Paths(
        config,
        data,
        runtime,
        home / "Audiobooks" / "Audible",
        home / "Audiobooks" / "Audible",
        home,
    )
    safe = tmp_path / "safe"
    safe.mkdir()
    assert books_dir_problem(safe, paths, home) is None
    assert (
        books_dir_problem(Path("relative"), paths, home)
        == "path must be absolute (or start with ~/)"
    )
    assert books_dir_problem(Path("/"), paths, home) == "path cannot be /"
    assert books_dir_problem(home, paths, home) == "path cannot be your home folder"
    assert (
        books_dir_problem(tmp_path, paths, home)
        == "path cannot contain plugin data or runtime files"
    )
    for forbidden in (config, data, runtime, paths.venv_dir):
        assert (
            books_dir_problem(forbidden, paths, home)
            == "path cannot contain plugin data or runtime files"
        )
    assert books_dir_problem(data / "nested", paths, home) is None
    assert (
        books_dir_problem(data, paths, home)
        == "path cannot contain plugin data or runtime files"
    )
    assert books_dir_problem(paths.venv_dir / "nested", paths, home).startswith(
        "path cannot be inside"
    )
    assert (
        books_dir_problem(paths.venv_dir, paths, home)
        == "path cannot contain plugin data or runtime files"
    )
    assert books_dir_problem(config / "inside", paths, home).startswith(
        "path cannot be inside"
    )
    assert books_dir_problem(runtime / "inside", paths, home).startswith(
        "path cannot be inside"
    )
    assert books_dir_problem(home / ".audible", paths, home).startswith(
        "path cannot be inside"
    )
    for system_dir in (
        "/proc",
        "/sys",
        "/dev",
        "/boot",
        "/etc",
        "/usr",
        "/bin",
        "/sbin",
        "/lib",
        "/lib64",
    ):
        assert books_dir_problem(Path(system_dir), paths, home).startswith(
            "path cannot be inside a system directory"
        )
        assert books_dir_problem(Path(system_dir) / "books", paths, home).startswith(
            "path cannot be inside a system directory"
        )
    assert books_dir_problem(home / "not-yet-created", paths, home) is None
    file_path = tmp_path / "a-file"
    file_path.write_text("x", encoding="utf-8")
    assert (
        books_dir_problem(file_path, paths, home)
        == "path exists and is not a directory"
    )
    assert (
        books_dir_problem(file_path / "books", paths, home)
        == "nearest existing ancestor is not a directory"
    )
    good_link = tmp_path / "good-link"
    good_link.symlink_to(safe)
    assert books_dir_problem(good_link, paths, home) is None
    forbidden_link = tmp_path / "forbidden-link"
    forbidden_link.symlink_to(config)
    assert books_dir_problem(forbidden_link, paths, home).startswith(
        "path cannot contain"
    )
    assert (
        books_dir_problem(Path("/has\0nul"), paths, home)
        == "path contains a NUL character"
    )


def test_paths_from_env_expands_home_and_falls_back_on_unsafe_values(env):
    home = Path(env["HOME"])
    env["OMARCHY_AUDIBLE_BOOKS_DIR"] = "  ~/Books  "
    selected = Paths.from_env(env)
    assert selected.books_dir == home / "Books"
    assert selected.books_dir_problem is None

    env["OMARCHY_AUDIBLE_BOOKS_DIR"] = "/"
    rejected = Paths.from_env(env)
    assert rejected.books_dir == (home / "Audiobooks" / "Audible")
    assert rejected.books_dir_problem == "path cannot be /"


def test_status_books_dir_without_override_matches_main_default(env, run_cli, events):
    env.pop("OMARCHY_AUDIBLE_BOOKS_DIR")
    result = run_cli("status", extra_env={"OMARCHY_AUDIBLE_BOOKS_DIR": ""})
    status = next(event for event in events(result) if event["type"] == "status")
    assert status["books_dir"] == str(Path(env["HOME"]) / "Audiobooks" / "Audible")


def test_fake_status_never_scans_real_default_without_record(env, monkeypatch, capsys):
    real_default = Path(env["HOME"]) / "Audiobooks" / "Audible"
    _seed_book(real_default)
    fake_paths = Paths.from_env(env, fake=True)
    scanned = []
    monkeypatch.setattr(commands, "scan_local", lambda path: scanned.append(path) or [])
    assert commands.cmd_status([], command="status", fake=True, paths=fake_paths) == 0
    status = json.loads(capsys.readouterr().out.splitlines()[0])
    assert status["type"] == "status"
    assert status["old_books"] is None
    assert real_default not in scanned


def test_fake_status_does_not_report_a_seeded_real_default(env, run_cli, events):
    real_default = Path(env["HOME"]) / "Audiobooks" / "Audible"
    _seed_book(real_default)
    status = next(
        event
        for event in events(
            run_cli("status", fake=True, extra_env={"OMARCHY_AUDIBLE_BOOKS_DIR": ""})
        )
        if event["type"] == "status"
    )
    assert status["old_books"] is None


def test_fake_default_override_is_treated_as_unset(env, run_cli, events):
    status = next(
        event
        for event in events(
            run_cli(
                "status",
                fake=True,
                extra_env={"OMARCHY_AUDIBLE_BOOKS_DIR": "~/Audiobooks/Audible"},
            )
        )
        if event["type"] == "status"
    )
    fake = Paths.from_env(env, fake=True)
    assert status["books_dir"] == str(fake.data_dir / "books")
    assert status["books_dir_problem"] is None


@pytest.mark.parametrize(
    "override,expected",
    [
        ("/", "path cannot be /"),
        ("relative/path", "path must be absolute (or start with ~/)"),
        ("/tmp/outside", "fake mode only allows paths inside its data directory"),
    ],
)
def test_fake_invalid_books_dir_keeps_specific_reason(env, override, expected):
    selected = Paths.from_env({**env, "OMARCHY_AUDIBLE_BOOKS_DIR": override}, fake=True)
    assert selected.books_dir == selected.default_books_dir
    assert selected.books_dir_problem == expected


def test_fake_status_ignores_record_outside_fake_data(
    env, fake_paths, run_cli, events, tmp_path
):
    fake_paths.books_location_file.write_text(json.dumps({"books_dir": str(tmp_path)}))
    status = next(
        event
        for event in events(run_cli("status", fake=True))
        if event["type"] == "status"
    )
    assert status["old_books"] is None
    assert status["books_location_recorded"] is False


def test_status_old_books_record_cases(env, paths, run_cli, events, tmp_path):
    old = Path(env["HOME"]) / "Audiobooks" / "Audible"
    _seed_book(old)
    status = lambda extra=None: next(
        e for e in events(run_cli("status", extra_env=extra)) if e["type"] == "status"
    )
    missing = status()
    assert missing["old_books"] == {"dir": str(old), "count": 1}
    assert missing["books_location_recorded"] is False

    paths.books_location_file.parent.mkdir(parents=True, exist_ok=True)
    paths.books_location_file.write_text(
        json.dumps({"books_dir": str(paths.books_dir)})
    )
    equal = status()
    assert equal["old_books"] is None and equal["books_location_recorded"] is True

    paths.books_location_file.write_text(json.dumps({"books_dir": str(old)}))
    different = status()
    assert different["old_books"]["count"] == 1
    assert different["books_location_recorded"] is False

    (old / "B00FAKE01" / "book.m4b").unlink()
    assert status()["old_books"] is None
    paths.books_location_file.write_text(
        json.dumps({"books_dir": str(tmp_path / "missing")})
    )
    assert status()["old_books"] is None


def test_ack_contract_writes_effective_books_dir(env, run_cli, events, fake_paths):
    result = run_cli("books-location-ack", fake=True)
    assert [event["type"] for event in events(result)] == ["done"]
    assert json.loads(fake_paths.books_location_file.read_text()) == {
        "books_dir": str(fake_paths.books_dir)
    }
    after_ack = next(
        event
        for event in events(run_cli("status", fake=True))
        if event["type"] == "status"
    )
    assert after_ack["books_location_recorded"] is True
    assert after_ack["old_books"] is None
    invalid = run_cli("books-location-ack", str(fake_paths.books_dir), fake=True)
    assert invalid.returncode != 0
    assert events(invalid)[-1]["type"] == "error"


@pytest.mark.parametrize(
    "count,expected",
    [
        (1, "1 downloaded book is still in ~/Old"),
        (2, "2 downloaded books are still in ~/Old"),
    ],
)
def test_books_location_notice_text(count, expected):
    module = qjs.load("BooksLocation")
    text = module.call(
        "oldBooksText",
        {"dir": "/home/me/Old", "count": count},
        "/home/me/New",
        "/home/me",
    )
    assert text.startswith(expected)
    assert text.endswith(
        "move its folder into ~/New or change booksDir back."
        if count == 1
        else "move their folders into ~/New or change booksDir back."
    )
    assert (
        module.call(
            "problemText", "path must be absolute", "/home/me/Audiobooks", "/home/me"
        )
        == "booksDir was not used: path must be absolute. Books are in ~/Audiobooks."
    )
    empty = {"old_books": None, "books_location_recorded": False}
    occupied = {"old_books": {"count": 1}, "books_location_recorded": False}
    recorded = {"old_books": None, "books_location_recorded": True}
    assert module.call("shouldAck", empty, False, True) is True
    assert module.call("shouldAck", empty, True, True) is False
    assert module.call("shouldAck", empty, False, False) is False
    assert module.call("shouldAck", occupied, False, True) is False
    assert module.call("shouldAck", recorded, False, True) is False
    assert module.call("shouldShowOldBooks", occupied, False) is False
    assert module.call("shouldShowOldBooks", occupied, True) is True
    assert (
        module.call("shouldShowProblem", {"books_dir_problem": "bad"}, False) is False
    )
    assert module.call("shouldShowProblem", {"books_dir_problem": "bad"}, True) is True


def test_fake_books_dir_override_is_confined_to_fake_data(
    env, run_cli, events, tmp_path
):
    fake = Paths.from_env(env, fake=True)
    inside = fake.data_dir / "books-alt"
    outside = tmp_path / "elsewhere"
    accepted = next(
        event
        for event in events(
            run_cli(
                "status",
                fake=True,
                extra_env={"OMARCHY_AUDIBLE_BOOKS_DIR": str(inside)},
            )
        )
        if event["type"] == "status"
    )
    ignored = next(
        event
        for event in events(
            run_cli(
                "status",
                fake=True,
                extra_env={"OMARCHY_AUDIBLE_BOOKS_DIR": str(outside)},
            )
        )
        if event["type"] == "status"
    )
    assert accepted["books_dir"] == str(inside)
    assert accepted["books_dir_problem"] is None
    assert ignored["books_dir"] == str(fake.books_dir)
    assert ignored["books_dir_problem"]
