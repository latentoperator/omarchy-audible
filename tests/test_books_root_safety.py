"""B03: effective books roots fail closed, using only synthetic HOME/XDG trees."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omarchy_audible import commands, download
from omarchy_audible.errors import PipelineError
from omarchy_audible.paths import Paths

ASIN = "B00FAKE01"


@pytest.fixture
def isolated_env(env, tmp_path, monkeypatch):
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    env["TMPDIR"] = str(scratch)
    env["OMARCHY_AUDIBLE_BOOKS_DIR"] = ""
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return env


def _seed(root: Path) -> Path:
    directory = root / ASIN
    directory.mkdir(parents=True)
    (directory / "book.m4b").write_bytes(b"synthetic outside audio")
    (directory / "meta.json").write_text('{"title":"Invented sentinel"}')
    directory.chmod(0o755)
    return directory


def _snapshot(directory: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(path.relative_to(directory)): (path.read_bytes(), path.stat().st_mode)
        for path in directory.rglob("*")
        if path.is_file()
    }


def _unsafe_default(env, fake, destination, override):
    initial = Paths.from_env(env, fake=fake)
    roots = {
        "outside": Path(env["HOME"]) / "synthetic-outside",
        "data": initial.data_dir,
        "config": initial.config_dir / "nested",
        "runtime": initial.runtime_dir / "nested",
        "venv": initial.venv_dir / "nested",
    }
    root = roots[destination]
    directory = _seed(root)
    initial.default_books_dir.parent.mkdir(parents=True, exist_ok=True)
    initial.default_books_dir.symlink_to(root, target_is_directory=True)
    env["OMARCHY_AUDIBLE_BOOKS_DIR"] = override
    return Paths.from_env(env, fake=fake), directory


UNSAFE_DEFAULTS = [
    (True, "outside", ""),
    (True, "outside", "~/Audiobooks/Audible"),
    (True, "outside", "relative"),
    (True, "config", ""),
    (True, "runtime", ""),
    (True, "venv", ""),
    (False, "data", ""),
    (False, "data", "relative"),
    (False, "config", ""),
    (False, "runtime", ""),
    (False, "venv", ""),
]


@pytest.mark.parametrize("fake,destination,override", UNSAFE_DEFAULTS)
def test_unsafe_default_is_not_an_effective_root(
    isolated_env, fake, destination, override
):
    paths, _ = _unsafe_default(isolated_env, fake, destination, override)
    assert paths.books_dir is None
    assert paths.books_dir_problem


@pytest.mark.parametrize("fake,destination,override", UNSAFE_DEFAULTS)
@pytest.mark.parametrize("command", ["get", "local", "play-info", "remove"])
def test_book_commands_preserve_outside_sentinels(
    isolated_env, fake, destination, override, command, capsys
):
    paths, directory = _unsafe_default(isolated_env, fake, destination, override)
    before = _snapshot(directory)
    args = [] if command == "local" else [ASIN]
    # Even the real-layout cases execute only the synthetic, offline pipeline.
    result = commands.REGISTRY[command].handler(
        args, command=command, fake=True, paths=paths
    )
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert _snapshot(directory) == before
    assert sorted(path.name for path in directory.iterdir()) == [
        "book.m4b",
        "meta.json",
    ]
    assert result != 0
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "unsafe_path"
    assert not any(event["type"] in ("local", "play_info", "done") for event in events)
    assert "Invented sentinel" not in json.dumps(events)


@pytest.mark.parametrize("fake,destination,override", UNSAFE_DEFAULTS)
def test_direct_download_refuses_unsafe_root(isolated_env, fake, destination, override):
    paths, directory = _unsafe_default(isolated_env, fake, destination, override)
    before = _snapshot(directory)
    with pytest.raises(PipelineError) as error:
        download.run_get(ASIN, paths, fake=True, emit=lambda *a, **kw: None)
    assert error.value.code == "unsafe_path"
    assert _snapshot(directory) == before


@pytest.mark.parametrize("fake,destination,override", UNSAFE_DEFAULTS)
def test_unsafe_default_is_never_scanned_as_old_folder(
    isolated_env, fake, destination, override, monkeypatch
):
    paths, directory = _unsafe_default(isolated_env, fake, destination, override)
    before = _snapshot(directory)
    safe = paths.data_dir / "safe-books" if fake else paths.home_dir / "safe-books"
    isolated_env["OMARCHY_AUDIBLE_BOOKS_DIR"] = str(safe)
    selected = Paths.from_env(isolated_env, fake=fake)
    scanned = []
    original = commands.scan_local

    def scan(root):
        scanned.append(root)
        return original(root)

    monkeypatch.setattr(commands, "scan_local", scan)
    location = commands._books_location(selected)
    assert scanned == []
    assert location["old_books"] is None
    assert _snapshot(directory) == before


@pytest.mark.parametrize("fake", [False, True])
@pytest.mark.parametrize("destination", ["config", "runtime", "venv", "outside"])
def test_unsafe_recorded_folder_is_never_scanned(
    isolated_env, fake, destination, monkeypatch
):
    if not fake and destination == "outside":
        # A real folder outside plugin data is supported; here use its data root.
        destination = "data"
    initial = Paths.from_env(isolated_env, fake=fake)
    targets = {
        "config": initial.config_dir / "nested",
        "runtime": initial.runtime_dir / "nested",
        "venv": initial.venv_dir / "nested",
        "outside": initial.home_dir / "synthetic-outside",
        "data": initial.data_dir,
    }
    target = targets[destination]
    directory = _seed(target)
    before = _snapshot(directory)
    link = initial.data_dir / "old-link" if fake else initial.home_dir / "old-link"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)
    initial.books_location_file.parent.mkdir(parents=True, exist_ok=True)
    initial.books_location_file.write_text(json.dumps({"books_dir": str(link)}))
    scanned = []
    monkeypatch.setattr(commands, "scan_local", lambda root: scanned.append(root) or [])
    location = commands._books_location(initial)
    assert scanned == []
    assert location["old_books"] is None
    assert location["books_location_recorded"] is False
    assert _snapshot(directory) == before


@pytest.mark.parametrize("fake", [False, True])
def test_ack_cannot_record_an_unsafe_default(isolated_env, fake, capsys):
    paths, _ = _unsafe_default(isolated_env, fake, "outside" if fake else "data", "")
    result = commands.cmd_books_location_ack(
        [], command="books-location-ack", fake=True, paths=paths
    )
    assert result != 0
    assert not paths.books_location_file.exists()
    assert json.loads(capsys.readouterr().out)["code"] == "unsafe_path"


@pytest.mark.parametrize("fake", [False, True])
@pytest.mark.parametrize("selection", ["default", "override"])
def test_safe_books_symlink_keeps_supported_spelling_and_io(
    isolated_env, fake, selection, capsys, ffmpeg_bin
):
    initial = Paths.from_env(isolated_env, fake=fake)
    target = (
        initial.data_dir / "safe-target" if fake else initial.home_dir / "safe-target"
    )
    target.mkdir(parents=True)
    link = (
        initial.default_books_dir if selection == "default" else target.parent / "link"
    )
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)
    if selection == "override":
        isolated_env["OMARCHY_AUDIBLE_BOOKS_DIR"] = str(link)
    selected = Paths.from_env(isolated_env, fake=fake)
    assert selected.books_dir == link
    assert selected.books_dir_problem is None
    assert commands.cmd_get([ASIN], command="get", fake=True, paths=selected) == 0
    assert (target / ASIN / "book.aaxc").is_file()
    capsys.readouterr()
    assert commands.cmd_local([], command="local", fake=True, paths=selected) == 0
    assert (
        json.loads(capsys.readouterr().out.splitlines()[0])["books"][0]["asin"] == ASIN
    )
    assert (
        commands.cmd_play_info([ASIN], command="play-info", fake=True, paths=selected)
        == 0
    )
    payload = json.loads(capsys.readouterr().out.splitlines()[0])
    assert payload["path"] == str(link / ASIN / "book.aaxc")
    # A supported root is also safe when used as the previously recorded folder.
    selected.books_location_file.parent.mkdir(parents=True, exist_ok=True)
    selected.books_location_file.write_text(json.dumps({"books_dir": str(link)}))
    isolated_env["OMARCHY_AUDIBLE_BOOKS_DIR"] = str(target.parent / "other-books")
    current = Paths.from_env(isolated_env, fake=fake)
    assert commands._books_location(current)["old_books"] == {
        "dir": str(link),
        "count": 1,
    }
    assert commands.cmd_remove([ASIN], command="remove", fake=True, paths=selected) == 0
    assert not (target / ASIN).exists()


@pytest.mark.parametrize("fake", [False, True])
@pytest.mark.parametrize("destination", ["config", "runtime", "venv", "escape"])
def test_unsafe_override_symlink_uses_only_safe_default(
    isolated_env, fake, destination, capsys, ffmpeg_bin
):
    initial = Paths.from_env(isolated_env, fake=fake)
    roots = {
        "config": initial.config_dir / "nested",
        "runtime": initial.runtime_dir / "nested",
        "venv": initial.venv_dir / "nested",
        "escape": initial.home_dir / "outside" if fake else initial.data_dir,
    }
    directory = _seed(roots[destination])
    before = _snapshot(directory)
    link = initial.data_dir / "override" if fake else initial.home_dir / "override"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(roots[destination], target_is_directory=True)
    isolated_env["OMARCHY_AUDIBLE_BOOKS_DIR"] = str(link)
    selected = Paths.from_env(isolated_env, fake=fake)
    assert selected.books_dir == initial.default_books_dir
    assert selected.books_dir_problem
    assert commands.cmd_get([ASIN], command="get", fake=True, paths=selected) == 0
    capsys.readouterr()
    assert commands.cmd_remove([ASIN], command="remove", fake=True, paths=selected) == 0
    assert _snapshot(directory) == before


@pytest.mark.parametrize("command", ["get", "local", "play-info", "remove"])
def test_fake_cli_fails_closed_for_default_escape(
    isolated_env, command, run_cli, validate_stream
):
    _, directory = _unsafe_default(isolated_env, True, "outside", "")
    before = _snapshot(directory)
    args = [] if command == "local" else [ASIN]
    result = run_cli(command, *args, fake=True)
    parsed = validate_stream(result, expect_last="error")
    assert result.returncode != 0
    assert parsed[-1]["code"] == "unsafe_path"
    assert _snapshot(directory) == before


def test_fake_status_reports_unsafe_default_without_using_it(
    isolated_env, run_cli, validate_stream
):
    paths, _ = _unsafe_default(isolated_env, True, "outside", "")
    result = run_cli("status", fake=True)
    parsed = validate_stream(result, expect_last="done")
    assert result.returncode == 0
    assert parsed[0]["books_dir"] == str(paths.default_books_dir)
    assert parsed[0]["books_dir_problem"].startswith("no safe books directory:")
    assert parsed[0]["books_location_recorded"] is False
    assert parsed[0]["old_books"] is None


@pytest.mark.parametrize("fake", [False, True])
def test_safe_override_remains_usable_when_default_is_unsafe(isolated_env, fake):
    paths, _ = _unsafe_default(isolated_env, fake, "outside" if fake else "data", "")
    safe = paths.data_dir / "safe-books" if fake else paths.home_dir / "safe-books"
    isolated_env["OMARCHY_AUDIBLE_BOOKS_DIR"] = str(safe)
    selected = Paths.from_env(isolated_env, fake=fake)
    assert selected.books_dir == safe
    assert selected.books_dir_problem is None
