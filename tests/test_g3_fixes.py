"""G3 findings 1, 2, 5 and 6: wiring checks on the QML that the JS tests can't reach.

1. A fake-mode mpv must not block the real one: each mode has its own scope
   unit, and real mode stops a leftover fake one.
2. A play that fails must say so (a desktop notification and a Mini line).
5. Every ⏯ goes through ``Service.playPause`` so it can catch up first.
6. Author names use the drawer's text color, not ``Color.muted``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def function_body(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    depth = 0
    for i in range(source.index("{", start), len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    raise AssertionError(f"unterminated {name}")


# ---- 1: one scope unit per mode ----

def test_player_unit_name_is_a_property():
    player = read("qml/PlayerController.qml")
    assert 'property string unitName: "omarchy-audible-mpv"' in player
    assert '"--unit=" + unitName' in player
    assert "root.unitName + \".scope\"" in player
    assert '"omarchy-audible-mpv.scope"' not in player
    assert '"--unit=omarchy-audible-mpv"' not in player


def test_service_picks_the_unit_by_mode():
    service = read("Service.qml")
    assert 'unitName: root.fake ? "omarchy-audible-fake-mpv" : "omarchy-audible-mpv"' in service


def test_real_mode_stops_a_leftover_fake_player():
    service = read("Service.qml")
    assert '["systemctl", "--user", "stop", "omarchy-audible-fake-mpv.scope"]' in service
    body = function_body(service, "stopOtherModePlayer")
    assert "if (root.fake) return" in body


# ---- 2: a failed play is visible ----

def test_failed_play_notifies():
    service = read("Service.qml")
    assert "function onConnectionChanged()" in service
    body = function_body(service, "notifyPlayFailed")
    assert '"notify-send"' in body
    assert "Couldn't start playback" in body


def test_mini_shows_the_player_error():
    mini = read("qml/views/MiniView.qml")
    assert 'root.player.connection === "failed"' in mini
    assert "root.player.lastError" in mini


# ---- 5: every play/pause goes through the service ----

def test_no_view_toggles_the_player_directly():
    for rel in ("BarWidget.qml", "qml/views/MiniView.qml"):
        assert "player.toggle()" not in read(rel), rel


def test_play_pause_entry_points_use_the_service():
    bar = read("BarWidget.qml")
    assert bar.count("service.playPause()") == 2   # Space and middle-click
    assert "root.service.playPause()" in read("qml/views/MiniView.qml")
    service = read("Service.qml")
    ipc = service[service.index("IpcHandler {"):]
    assert "return root.playPause()" in function_body(ipc, "playPause")


def test_resume_reads_only_after_a_long_pause():
    service = read("Service.qml")
    body = function_body(service, "playPause")
    assert "Catchup.needsRead(pausedAtMs, Date.now())" in body
    assert "Catchup.prefetchUsable(prefetched, asin, Date.now())" in body
    assert 'run("position-get", [asin], "catchup")' in service
    # A pause records when it happened.
    assert "root.pausedAtMs = Date.now()" in service


def test_catch_up_falls_back_after_the_timeout():
    service = read("Service.qml")
    assert "interval: Catchup.READ_TIMEOUT_MS" in service
    body = function_body(service, "resumeCaughtUp")
    assert "Catchup.jumpTarget(" in body
    assert "player.seekMs(target)" in body
    assert "player.resume()" in body
    # A switch to another book while reading must not resume the old one.
    assert "loadedAsin !== asin" in body


def test_opening_the_drawer_prefetches():
    service = read("Service.qml")
    assert "prefetchCatchup()" in function_body(service, "viewForOpen")


# ---- 6: author names readable ----

def test_author_names_are_not_muted():
    for rel in ("qml/components/BookRow.qml", "qml/views/MiniView.qml"):
        source = read(rel)
        block = source[:source.index("Format.names(")]
        block = source[block.rindex("Text {"):]
        block = block[:block.index("}")]
        assert "Color.muted" not in block, rel
        assert re.search(r"Qt\.rgba\(Color\.popups\.text\.r, Color\.popups\.text\.g, Color\.popups\.text\.b, 0\.75\)", block), rel
