"""P9 PR 2 — one home for each shared constant, and no reference to a constant that isn't there.

A typo in ``Glyphs.GLYPH_X`` gives a blank icon and nothing else fails, so the first tests read every
``.qml`` file and every ``.js`` file under ``qml/`` and check each ``Qualifier.UPPER_NAME`` in its
code: the qualifier must be a lib that file imports, and the name must be declared in that lib.
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
# Any `Qualifier.UPPER_NAME`, whether or not the file imports the qualifier.
# Qt's own enums (`Qt.Key_Escape`, `Text.AlignLeft`) are not all caps.
REFERENCE = re.compile(r"(?<![\w.])([A-Z]\w*)\.([A-Z][A-Z0-9_]*)\b")
# A `//` comment: at the start of a line or after a space, so `https://` stays.
COMMENT = re.compile(r"(?:^|(?<=\s))//.*$", re.MULTILINE)


def sources() -> list[pathlib.Path]:
    qml = sorted(REPO.glob("*.qml")) + sorted((REPO / "qml").rglob("*.qml"))
    return qml + sorted((REPO / "qml").rglob("*.js"))


def declared(lib: str) -> set[str]:
    path = LIB / f"{lib}.js"
    return (
        set(DECLARED.findall(path.read_text(encoding="utf-8")))
        if path.is_file()
        else set()
    )


def problems(text: str) -> list[str]:
    """Each `Qualifier.UPPER_NAME` in `text`'s code that won't resolve at runtime."""
    imports = {qualifier: lib for _, lib, qualifier in IMPORT.findall(text)}
    found = []
    for qualifier, name in REFERENCE.findall(COMMENT.sub("", text)):
        if qualifier not in imports:
            found.append(f"{qualifier}.{name}: {qualifier} is not imported")
        elif name not in declared(imports[qualifier]):
            found.append(f"{qualifier}.{name}: not declared in {imports[qualifier]}.js")
    return found


def test_the_scan_sees_the_constants():
    mini = (REPO / "qml/views/MiniView.qml").read_text(encoding="utf-8")
    assert ("Glyphs", "GLYPH_MOON") in REFERENCE.findall(mini)
    onboarding = (LIB / "Onboarding.js").read_text(encoding="utf-8")
    assert ("Panel", "VIEW_FULL") in REFERENCE.findall(COMMENT.sub("", onboarding))


def test_every_qualified_constant_resolves():
    found = {}
    for path in sources():
        bad = problems(path.read_text(encoding="utf-8"))
        if bad:
            found[str(path.relative_to(REPO))] = bad
    assert found == {}


@pytest.mark.parametrize(
    "rel,old,new,problem",
    [
        # A typo'd name, a typo'd qualifier and a dropped import, in a view,
        # a component and a lib (Codex, round 1).
        (
            "qml/views/MiniView.qml",
            "Glyphs.GLYPH_MOON",
            "Glyphs.GLYPH_MON",
            "Glyphs.GLYPH_MON: not declared in Glyphs.js",
        ),
        (
            "qml/views/MiniView.qml",
            "Glyphs.GLYPH_MOON",
            "Glyph.GLYPH_MOON",
            "Glyph.GLYPH_MOON: Glyph is not imported",
        ),
        (
            "qml/components/Cover.qml",
            'import "../lib/Glyphs.js" as Glyphs\n',
            "",
            "Glyphs.GLYPH_BOOK: Glyphs is not imported",
        ),
        (
            "qml/lib/Panel.js",
            "Glyphs.GLYPH_PAUSED",
            "Glyph.GLYPH_PAUSED",
            "Glyph.GLYPH_PAUSED: Glyph is not imported",
        ),
        (
            "qml/lib/Onboarding.js",
            '.import "Panel.js" as Panel\n',
            "",
            "Panel.VIEW_ONBOARDING: Panel is not imported",
        ),
    ],
)
def test_the_check_catches_a_broken_reference(rel, old, new, problem):
    text = (REPO / rel).read_text(encoding="utf-8")
    assert old in text and problems(text) == []
    assert problem in problems(text.replace(old, new, 1))


def test_comments_are_not_code_but_code_after_a_url_is():
    assert problems("// See `Glyph.GLYPH_X`.\nvar A = 1;  // Other.NAME\n") == []
    text = 'var A = "https://example.com/" + Glyph.GLYPH_X;\n'
    assert problems(text) == ["Glyph.GLYPH_X: Glyph is not imported"]


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
        (r"FINISH_TRAILING_MS", "Positions"),
    ],
)
def test_each_constant_has_one_home(pattern, home):
    homes = definitions(pattern)
    assert homes
    assert {name: libs for name, libs in homes.items() if libs != [home]} == {}


def test_every_glyph_is_one_icon_font_code_point():
    text = (LIB / "Glyphs.js").read_text(encoding="utf-8")
    glyphs = dict(re.findall(r'^var (GLYPH_[A-Z_]+) = "([^"]*)";$', text, re.MULTILINE))
    assert len(glyphs) == 20
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
