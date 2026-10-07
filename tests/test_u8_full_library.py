"""U8 — the Full view has the same Library button as Mini."""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent


def library_buttons(rel: str) -> list[str]:
    """Each Button block in a view that uses the Library glyph."""
    source = (REPO / rel).read_text(encoding="utf-8")
    blocks = re.findall(r"Button \{[^{}]*\}", source)
    return [b for b in blocks if "Mini.GLYPH_LIBRARY" in b]


def test_full_has_the_library_button():
    (full,) = library_buttons("qml/views/FullView.qml")
    assert 'tooltipText: "Library"' in full
    # Showing the Library leaves playback alone: no player call in the click.
    assert (
        "onClicked: if (root.service) root.service.showView(Panel.VIEW_LIBRARY)" in full
    )
    assert "player" not in full


def test_full_and_mini_buttons_do_the_same():
    (full,) = library_buttons("qml/views/FullView.qml")
    (mini,) = library_buttons("qml/views/MiniView.qml")

    def click(block: str) -> str:
        return re.search(r"onClicked: .*", block).group(0)

    assert click(full) == click(mini)


def test_the_library_button_sits_before_collapse_and_close():
    source = (REPO / "qml/views/FullView.qml").read_text(encoding="utf-8")
    library = source.index("Mini.GLYPH_LIBRARY")
    assert library < source.index("Player.GLYPH_COLLAPSE")
    assert library < source.index("Player.GLYPH_DISMISS")
