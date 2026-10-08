"""P9 PR 2 — one home for each shared constant, and no reference to a constant that isn't there.

A typo in ``Glyphs.GLYPH_X`` gives a blank icon and nothing else fails, so the first test reads every
``.qml`` file and every ``.js`` file under ``qml/`` and checks that each ``Qualifier.UPPER_NAME``
it uses is declared in the lib that qualifier imports.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
LIB = REPO / "qml" / "lib"

# `import "../lib/Mini.js" as Mini` in QML, `.import "Glyphs.js" as Glyphs` in a lib.
IMPORT = re.compile(
    r'^[ \t]*\.?import[ \t]+"([^"]*?)(\w+)\.js"[ \t]+as[ \t]+(\w+)', re.MULTILINE
)
DECLARED = re.compile(r"^var[ \t]+([A-Z][A-Z0-9_]*)\b", re.MULTILINE)


def sources() -> list[pathlib.Path]:
    qml = sorted(REPO.glob("*.qml")) + sorted((REPO / "qml").rglob("*.qml"))
    return qml + sorted((REPO / "qml").rglob("*.js"))


def declared(lib: str) -> set[str]:
    return set(DECLARED.findall((LIB / f"{lib}.js").read_text(encoding="utf-8")))


def uses() -> list[tuple[str, str, str, str]]:
    found = []
    for path in sources():
        text = path.read_text(encoding="utf-8")
        qualifiers = {q: lib for _, lib, q in IMPORT.findall(text)}
        for qualifier, lib in qualifiers.items():
            for name in re.findall(
                rf"(?<![\w.]){qualifier}\.([A-Z][A-Z0-9_]*)\b", text
            ):
                found.append((str(path.relative_to(REPO)), qualifier, lib, name))
    return found


def test_the_scan_sees_the_constants():
    found = uses()
    assert ("qml/views/MiniView.qml", "Glyphs", "Glyphs", "GLYPH_MOON") in found
    assert ("qml/lib/Onboarding.js", "Panel", "Panel", "VIEW_FULL") in found
    assert ("Service.qml", "Panel", "Panel", "VIEW_LIBRARY") in found


def test_every_qualified_constant_is_declared_in_its_lib():
    missing = sorted(
        {(f, f"{q}.{n}") for f, q, lib, n in uses() if n not in declared(lib)}
    )
    assert missing == []


def test_the_check_catches_a_typo():
    text = 'import "../lib/Glyphs.js" as Glyphs\nText { text: Glyphs.GLYPH_MON }\n'
    names = re.findall(r"(?<![\w.])Glyphs\.([A-Z][A-Z0-9_]*)\b", text)
    assert [n for n in names if n not in declared("Glyphs")] == ["GLYPH_MON"]


def definitions(pattern: str) -> dict[str, list[str]]:
    homes: dict[str, list[str]] = {}
    for path in sorted(LIB.glob("*.js")):
        for name in re.findall(
            rf"^var[ \t]+({pattern})\b", path.read_text(encoding="utf-8"), re.MULTILINE
        ):
            homes.setdefault(name, []).append(path.stem)
    return homes


@pytest.mark.parametrize(
    "pattern,home",
    [
        (r"GLYPH_[A-Z_]+", "Glyphs"),
        (r"VIEW_[A-Z_]+", "Panel"),
        (r"KEY_(?:ESCAPE|RETURN|ENTER)", "Drawer"),
        (r"(?:MIN|MAX)_(?:SPEED|VOLUME)", "Mpv"),
    ],
)
def test_each_constant_has_one_home(pattern, home):
    homes = definitions(pattern)
    assert homes
    assert {name: libs for name, libs in homes.items() if libs != [home]} == {}


def test_every_glyph_is_one_icon_font_code_point():
    text = (LIB / "Glyphs.js").read_text(encoding="utf-8")
    glyphs = dict(re.findall(r'^var (GLYPH_[A-Z_]+) = "([^"]*)";$', text, re.MULTILINE))
    assert len(glyphs) == 19
    # Font Awesome lives in the Private Use Area.
    assert all(len(g) == 1 and 0xE000 <= ord(g) <= 0xF8FF for g in glyphs.values())
    assert re.search(r"^\.import", text, re.MULTILINE) is None


def test_saved_settings_use_mpvs_ranges():
    playback = (LIB / "Playback.js").read_text(encoding="utf-8")
    start = playback.index("function withPlayerSettings(")
    body = playback[start : playback.index("\n}\n", start)]
    for name in ("MIN_VOLUME", "MAX_VOLUME", "MIN_SPEED", "MAX_SPEED"):
        assert f"Mpv.{name}" in body
    assert "130" not in body and "0.5" not in body
    assert (
        "// A copy of `state` with the push queue replaced.\nfunction withQueue("
        in playback
    )
