"""P8 — service and player fixes that live in QML (F17, F18, F19, F21, F22).

The decisions are in the pure libs and tested there; these check the wiring
in the QML objects, which the QJSEngine tests can't load.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent


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
                return source[start : i + 1]
    raise AssertionError(name)


def test_f17_auto_remove_unloads_the_loaded_book_first():
    # P9 PR 4: the auto-remove path moved to qml/Removals.qml.
    body = function_body(read("qml/Removals.qml"), "removeIfStillFinished")
    # The loaded book goes through removeBook (quit, then the unload list);
    # only a book that isn't loaded is removed straight away.
    assert (
        "if (asin === service.loadedAsin) service.removeBook(asin, Unload.PURPOSE_AUTO)"
        in body
    )
    assert 'else service.run("remove", [asin], Unload.PURPOSE_AUTO)' in body
    assert body.index("autoRemoveAllowed") < body.index("removeBook(asin")


def test_f18_the_retry_interval_follows_the_failures():
    sync = read("qml/PositionSync.qml")
    # The transition moved into Sync.step in P9 PR 7; failure-count growth and
    # its reset after a successful flush are exercised by the reducer vector.
    assert "readonly property int failedFlushes: reducerState.failedFlushes" in sync
    assert "retryIntervalMs: Sync.retryDelayMs(failedFlushes)" in sync
    service = read("Service.qml")
    # Reset on play and on panel open.
    assert "sync.resetRetry()" in function_body(service, "viewForOpen")
    playing = service[service.index("function onPlayingChanged()") :]
    playing = playing[: playing.index("function onVolumeChanged")]
    assert "sync.resetRetry()" in playing


def test_f19_the_picked_panel_reopens():
    service = read("Service.qml")
    assert "reopenSurface = openSurface()" in function_body(service, "startPicked")
    reopen = function_body(service, "reopenOnMini")
    assert "surfaces.indexOf(remembered) >= 0 ? remembered : primarySurface()" in reopen


def test_f21_mpv_starts_with_the_saved_volume_and_speed():
    player = read("qml/PlayerController.qml")
    assert '"--speed=" + initialSpeed' in function_body(player, "launchMpv")
    service = read("Service.qml")
    assert "initialVolume: Mpv.startVolume(store.doc.volume" in service
    assert "initialSpeed: Mpv.startSpeed(store.doc.speed, root.defaultSpeed)" in service
    note = function_body(service, "noteSettings")
    assert "if (!player.connected) return" in note
    assert "Mpv.userVolume(player.volume, player.fadeBaseVolume)" in note
    assert "store.setPlayerSettings(" in function_body(service, "saveSettings")


def test_f22_a_disconnect_forgets_the_fade_base():
    # P9 PR 9: the disconnect's branch of onConnectedChanged is now
    # PlayerMachine's, which emits forget_sleep after reset_state; the
    # controller's handler for it keeps the order. As behaviour:
    # test_player_qml's unexpected-exit test, with a fade in progress.
    player = read("qml/PlayerController.qml")
    forget = player[player.index('type === "forget_sleep"') :]
    forget = forget[: forget.index("} else if")]
    assert forget.index("sleepTimer = null") < forget.index("fadeBaseVolume = -1")
    machine = read("qml/lib/PlayerMachine.js")
    lost = machine[machine.index("_machine.disconnected = function") :]
    lost = lost[: lost.index("\n};\n")]
    assert lost.index('{ "type": "reset_state" }') < lost.index(
        '{ "type": "forget_sleep" }'
    )


def test_f23_pause_holds_and_resume_restarts_the_timer():
    player = read("qml/PlayerController.qml")
    assert "Mpv.holdSleepTimer(sleepTimer, Date.now())" in player
    assert "Mpv.resumeSleepTimer(sleepTimer, Date.now())" in player
    assert "Mpv.minutesSleepTimer(minutes, Date.now(), playing)" in function_body(
        player, "setSleepTimer"
    )


def test_f23_pausing_in_the_fade_keeps_the_timer():
    # Codex review of 172fd97: pausing in the last seconds cancelled it.
    player = read("qml/PlayerController.qml")
    handler = player[player.index("onPlayingChanged: {") :]
    handler = handler[: handler.index("\n  }\n")]
    assert "cancelSleep()" not in handler
    assert handler.index("endFade()") < handler.index("Mpv.holdSleepTimer(")
    end = function_body(player, "endFade")
    assert "setVolume(fadeBaseVolume)" in end and "fadeBaseVolume = -1" in end


def test_f21_pending_settings_are_saved_before_quit_and_play():
    # Codex review of 172fd97: a change within the debounce, then quit and
    # play again, started mpv with the old settings.
    service = read("Service.qml")
    quit_ = function_body(service, "quitPlayer")
    assert quit_.index("saveSettings()") < quit_.index("player.quit()")
    play = function_body(service, "playNow")
    assert play.index("saveSettings()") < play.index("run(PlayRequest.COMMAND")


def test_f18_push_state_reports_the_backoff_beside_the_stale_run():
    # The F18 evidence fields join P6's; the rebase onto P6 must keep both.
    push = function_body(read("qml/ServiceIpc.qml"), "pushState")
    for field in ('"staleCount"', '"staleNotice"', '"failedFlushes"', '"retryMs"'):
        assert field in push, field
