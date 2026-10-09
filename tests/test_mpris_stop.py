"""MPRIS commands are external player actions; keep unload handling safe."""

from pathlib import Path

from qjs import load

ROOT = Path(__file__).resolve().parents[1]


def test_external_unload_service_saves_before_existing_stop_cleanup():
    service = (ROOT / "Service.qml").read_text(encoding="utf-8")
    handler = service.split("function onExternalUnload()", 1)[1].split("\n    }", 1)[0]
    assert "Playback.externalUnload(" in handler
    assert handler.index(
        "root.savePosition(root.snapAsin, root.snapMs, true)"
    ) < handler.index("root.quitPlayer()")
    assert "root.savePosition(root.snapAsin, root.snapMs, true)" in handler


def test_service_launches_with_status_script_and_catalog_title():
    service = (ROOT / "Service.qml").read_text(encoding="utf-8")
    assert (
        'mprisScript: root.status && typeof root.status.mpris_script === "string"'
        in service
    )
    play_info = service.split("function startPlayInfo(job, record)", 1)[1].split(
        "\n  }", 1
    )[0]
    assert '"title": row ? row.title : ""' in play_info


def test_mpris_unload_decision_vectors():
    playback = load("Playback")
    assert playback.call("externalUnload", True, True, False, False, True, "B0A")
    assert not playback.call("externalUnload", True, True, False, False, False, "B0A")
    assert not playback.call("externalUnload", True, True, False, True, True, "B0A")
    assert not playback.call("externalUnload", True, False, False, False, True, "B0A")
