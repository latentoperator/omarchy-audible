"""B8 — fake mode resolves to its own folder tree (never the real plugin tree).

``--fake`` must read and write ``<root>/omarchy-audible-fake`` and ignore
``OMARCHY_AUDIBLE_BOOKS_DIR``, so development against the fake library cannot
clobber a real login, catalog, remote cache or downloaded book. These tests seed
a real-mode layout, run the whole command surface in fake mode, and assert the
real tree is byte- and mtime-identical afterward.
"""

from __future__ import annotations

from pathlib import Path

from omarchy_audible.paths import FAKE_DIR_NAME, PLUGIN_DIR_NAME, Paths

from test_contract import COMMAND_CASES


def _snapshot(roots: tuple[Path, ...]) -> dict[str, tuple[str, int, bytes]]:
    """Every dir and file under ``roots``: kind, mtime and bytes."""
    seen: dict[str, tuple[str, int, bytes]] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in (root, *sorted(root.rglob("*"))):
            stat = path.lstat()
            if path.is_dir():
                seen[str(path)] = ("dir", stat.st_mtime_ns, b"")
            else:
                seen[str(path)] = ("file", stat.st_mtime_ns, path.read_bytes())
    return seen


def _real_roots(env: dict[str, str]) -> tuple[Path, ...]:
    real = Paths.from_env(env)
    return (real.config_dir, real.data_dir, real.runtime_dir, real.books_dir)


def _seed_real_layout(paths: Paths) -> None:
    """The layout a real login, sync and download leave behind."""
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    (paths.config_dir / "auth.json").write_text('{"fake": "auth"}', encoding="utf-8")
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    (paths.data_dir / "catalog.json").write_text('{"schema": 1, "books": []}', encoding="utf-8")
    (paths.data_dir / "remote.json").write_text(
        '{"B00REAL01": {"ms": 1, "updated_at": null}}', encoding="utf-8"
    )
    book = paths.books_dir / "B00REAL01"
    book.mkdir(parents=True, exist_ok=True)
    (book / "book.m4b").write_bytes(b"real audio")
    (book / "meta.json").write_text('{"asin": "B00REAL01"}', encoding="utf-8")


def test_paths_from_env_separates_the_fake_roots(env):
    real = Paths.from_env(env)
    fake = Paths.from_env(env, fake=True)

    config_root = Path(env["XDG_CONFIG_HOME"])
    data_root = Path(env["XDG_DATA_HOME"])
    runtime_root = Path(env["XDG_RUNTIME_DIR"])

    assert real.config_dir == config_root / PLUGIN_DIR_NAME
    assert real.data_dir == data_root / PLUGIN_DIR_NAME
    assert real.runtime_dir == runtime_root / PLUGIN_DIR_NAME
    assert real.books_dir == Path(env["OMARCHY_AUDIBLE_BOOKS_DIR"])

    assert fake.config_dir == config_root / FAKE_DIR_NAME
    assert fake.data_dir == data_root / FAKE_DIR_NAME
    assert fake.runtime_dir == runtime_root / FAKE_DIR_NAME
    assert fake.books_dir == data_root / FAKE_DIR_NAME / "books"
    assert fake != real


def test_status_reports_the_resolved_dirs_in_both_modes(env, run_cli, events):
    real_status = next(
        event for event in events(run_cli("status")) if event["type"] == "status"
    )
    fake_status = next(
        event for event in events(run_cli("status", fake=True)) if event["type"] == "status"
    )

    real = Paths.from_env(env)
    fake = Paths.from_env(env, fake=True)
    for event, expected in ((real_status, real), (fake_status, fake)):
        assert event["config_dir"] == str(expected.config_dir)
        assert event["data_dir"] == str(expected.data_dir)
        assert event["runtime_dir"] == str(expected.runtime_dir)
        assert event["books_dir"] == str(expected.books_dir)


def test_fake_mode_ignores_the_books_dir_override(env, run_cli, events, tmp_path):
    override = tmp_path / "elsewhere"
    fake = Paths.from_env(env, fake=True)
    status = next(
        event
        for event in events(
            run_cli("status", fake=True, extra_env={"OMARCHY_AUDIBLE_BOOKS_DIR": str(override)})
        )
        if event["type"] == "status"
    )
    assert status["books_dir"] == str(fake.books_dir)
    assert status["books_dir"] != str(override)


def test_every_fake_command_leaves_the_real_tree_untouched(env, run_cli):
    real = Paths.from_env(env)
    _seed_real_layout(real)
    roots = _real_roots(env)
    before = _snapshot(roots)
    assert before  # the real layout really exists

    for command, args, stdin in COMMAND_CASES:
        run_cli(command, *args, fake=True, stdin=stdin)

    after = _snapshot(roots)
    assert after == before


def test_fake_sync_writes_only_into_the_fake_data_dir(env, run_cli):
    real = Paths.from_env(env)
    _seed_real_layout(real)
    roots = _real_roots(env)
    before = _snapshot(roots)

    assert run_cli("sync", fake=True).returncode == 0

    fake = Paths.from_env(env, fake=True)
    assert fake.catalog_file.is_file()
    assert fake.remote_file.is_file()
    assert _snapshot(roots) == before


def test_fake_get_writes_only_into_the_fake_books_dir(env, run_cli, ffmpeg_bin):
    real = Paths.from_env(env)
    _seed_real_layout(real)
    roots = _real_roots(env)
    before = _snapshot(roots)

    result = run_cli("get", "B00FAKE01", fake=True)
    assert result.returncode == 0, result.stderr

    fake = Paths.from_env(env, fake=True)
    assert (fake.books_dir / "B00FAKE01" / "book.aaxc").is_file()
    assert _snapshot(roots) == before
