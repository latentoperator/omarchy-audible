"""R8 — the shared transport row exposes the service Stop path."""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent


def test_stop_glyph_is_declared_once() -> None:
    glyphs = (REPO / "qml" / "lib" / "Glyphs.js").read_text(encoding="utf-8")
    declared = re.findall(r'^var GLYPH_STOP = "(.*?)";$', glyphs, re.MULTILINE)
    assert len(declared) == 1
    assert len(declared[0]) == 1
    assert ord(declared[0]) == 0xF04D


def test_transport_row_stop_is_enabled_for_loaded_books_and_calls_service() -> None:
    source = (REPO / "qml" / "components" / "TransportRow.qml").read_text(
        encoding="utf-8"
    )
    blocks = re.findall(r"  Button \{.*?\n  \}", source, re.DOTALL)
    stop = [block for block in blocks if 'tooltipText: "Stop"' in block]
    assert len(stop) == 1
    assert "enabled: root.loaded" in stop[0]
    assert "iconText: Glyphs.GLYPH_STOP" in stop[0]
    assert "onClicked: root.service.quitPlayer()" in stop[0]
    assert blocks.index(stop[0]) == len(blocks) - 1


def test_path_change_wires_the_unload_decision_to_panel_library_rule() -> None:
    service = (REPO / "Service.qml").read_text(encoding="utf-8")
    assert "function onPathChanged()" in service
    assert "Panel.libraryAfterUnload(player.loaded, player.wanted)" in service
    assert "root.showView(root.view)" in service
    assert "function showView(name)" in service
