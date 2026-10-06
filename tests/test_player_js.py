"""U5/U6 — ``qml/lib/Player.js``: chapter, speed and scrub-bar decisions."""

from __future__ import annotations

import pytest

import qjs

CHAPTERS = [
    {"title": "Opening", "startMs": 0},
    {"title": "  ", "startMs": 60000},
    {"title": " Middle ", "startMs": 180000},
]


@pytest.fixture(scope="module")
def player() -> qjs.JsModule:
    return qjs.load("Player")


@pytest.mark.parametrize("index,label", [
    (0, "Opening"),
    (1, "Chapter 2"),
    (2, "Middle"),
    (3, ""),
    (-1, ""),
    (1.5, ""),
    (None, ""),
    ("0", ""),
])
def test_chapter_label(player, index, label):
    assert player.call("chapterLabel", CHAPTERS, index) == label


@pytest.mark.parametrize("chapters", [None, [], "Opening", {"0": {"title": "x"}}])
def test_chapter_label_no_chapters(player, chapters):
    assert player.call("chapterLabel", chapters, 0) == ""


@pytest.mark.parametrize("chapter,label", [
    ({"title": None, "startMs": 0}, "Chapter 1"),
    ({"startMs": 0}, "Chapter 1"),
    (None, "Chapter 1"),
    ({"title": 7, "startMs": 0}, "Chapter 1"),
    ({"title": "<b>Markup</b>", "startMs": 0}, "<b>Markup</b>"),
])
def test_chapter_label_odd_entries(player, chapter, label):
    assert player.call("chapterLabel", [chapter], 0) == label


def test_chapter_label_long_title_is_kept_whole(player):
    # The view elides; the label never cuts.
    title = "A" * 80
    assert player.call("chapterLabel", [{"title": title, "startMs": 0}], 0) == title


def test_chapter_rows(player):
    assert player.call("chapterRows", CHAPTERS, 300000) == [
        {"index": 0, "label": "Opening", "startMs": 0, "durationMs": 60000},
        {"index": 1, "label": "Chapter 2", "startMs": 60000, "durationMs": 120000},
        {"index": 2, "label": "Middle", "startMs": 180000, "durationMs": 120000},
    ]


def test_chapter_rows_unknown_book_length(player):
    rows = player.call("chapterRows", CHAPTERS, 0)
    assert rows[2]["durationMs"] == -1
    assert rows[0]["durationMs"] == 60000


def test_chapter_rows_malformed_entries_keep_indexes(player):
    chapters = [{"title": "A", "startMs": 0}, None, {"title": "C", "startMs": "x"},
                {"title": "D", "startMs": 90000}]
    rows = player.call("chapterRows", chapters, 120000)
    assert [r["index"] for r in rows] == [0, 1, 2, 3]
    assert [r["label"] for r in rows] == ["A", "Chapter 2", "C", "D"]
    assert rows[1]["startMs"] == -1 and rows[1]["durationMs"] == -1
    assert rows[0]["durationMs"] == -1  # next start unknown
    assert rows[3]["durationMs"] == 30000


def test_chapter_rows_out_of_order_start_is_unknown_duration(player):
    rows = player.call("chapterRows", [{"title": "A", "startMs": 5000}, {"title": "B", "startMs": 1000}], 9000)
    assert rows[0]["durationMs"] == -1


@pytest.mark.parametrize("chapters", [None, [], "x", 7])
def test_chapter_rows_empty(player, chapters):
    assert player.call("chapterRows", chapters, 1000) == []


def test_chapter_rows_long_book(player):
    count = 150
    chapters = [{"title": f"Part {i + 1}", "startMs": i * 600000} for i in range(count)]
    rows = player.call("chapterRows", chapters, count * 600000)
    assert len(rows) == count
    assert rows[-1] == {"index": count - 1, "label": f"Part {count}",
                        "startMs": (count - 1) * 600000, "durationMs": 600000}
    assert all(r["durationMs"] == 600000 for r in rows)


@pytest.mark.parametrize("index,count,delta,ok", [
    (0, 3, 1, True),
    (0, 3, -1, False),
    (2, 3, 1, False),
    (2, 3, -1, True),
    (1, 3, 1, True),
    (-1, 3, 1, False),
    (0, 0, 1, False),
    (0, 1, 1, False),
    (0, 3, 2, False),
    (0, 3, 0, False),
    (None, 3, 1, False),
    (0, None, 1, False),
])
def test_can_jump_chapter(player, index, count, delta, ok):
    assert player.call("canJumpChapter", index, count, delta) is ok


@pytest.mark.parametrize("speed,label", [
    (1, "1.0×"),
    (1.0, "1.0×"),
    (0.75, "0.75×"),
    (1.25, "1.25×"),
    (1.5, "1.5×"),
    (2, "2.0×"),
    (2.5, "2.5×"),
    (3, "3.0×"),
    (1.05, "1.05×"),
    (1.1, "1.1×"),
    (1.2999999999, "1.3×"),
    (0, "1.0×"),
    (-1, "1.0×"),
    (None, "1.0×"),
    ("1.5", "1.0×"),
])
def test_speed_label(player, speed, label):
    assert player.call("speedLabel", speed) == label


@pytest.mark.parametrize("speed,next_speed", [
    (0.75, 1.0),
    (1.0, 1.25),
    (1.25, 1.5),
    (1.5, 1.75),
    (1.75, 2.0),
    (2.0, 2.5),
    (2.5, 3.0),
    (3.0, 0.75),
    # Not a preset: snap up to the next preset.
    (0.5, 0.75),
    (0.8, 1.0),
    (1.1, 1.25),
    (1.3, 1.5),
    (2.9, 3.0),
    (3.5, 0.75),
    # mpv's float for a preset still counts as that preset.
    (1.2500000001, 1.5),
    (1.2499999999, 1.5),
    # ...but a real non-preset speed just under a preset snaps up to it.
    (1.2495, 1.25),
    (2.999, 3.0),
    (0.7499, 0.75),
    # Bad input.
    (0, 1.0),
    (-2, 1.0),
    (None, 1.0),
    ("2", 1.0),
])
def test_next_speed(player, speed, next_speed):
    assert player.call("nextSpeed", speed) == pytest.approx(next_speed)


def test_next_speed_full_cycle(player):
    speed = 0.75
    seen = []
    for _ in range(8):
        seen.append(speed)
        speed = player.call("nextSpeed", speed)
    assert seen == [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
    assert speed == 0.75


def test_nan_and_infinity(player):
    assert player.evaluate("nextSpeed(NaN)") == 1.0
    assert player.evaluate("speedLabel(Infinity)") == "1.0×"
    assert player.evaluate("fraction(NaN, 1000)") == 0
    assert player.evaluate("positionAt(0.5, Infinity)") == 0
    assert player.evaluate("seekSettled(NaN, 1000)") is False


def test_tick_fractions(player):
    assert player.call("tickFractions", CHAPTERS, 300000) == [0.2, 0.6]


@pytest.mark.parametrize("chapters,duration", [
    (None, 300000),
    ([], 300000),
    (CHAPTERS, 0),
    (CHAPTERS, None),
    ([{"title": "only", "startMs": 0}], 300000),
])
def test_tick_fractions_empty(player, chapters, duration):
    assert player.call("tickFractions", chapters, duration) == []


def test_tick_fractions_skip_bad_and_out_of_range(player):
    chapters = [{"startMs": 0}, {"startMs": -5}, None, {"startMs": 400000}, {"startMs": 150000}]
    assert player.call("tickFractions", chapters, 300000) == [0.5]


def test_tick_fractions_too_many_chapters(player):
    many = [{"title": "", "startMs": i * 1000} for i in range(41)]
    assert player.call("tickFractions", many, 41000) == []
    assert len(player.call("tickFractions", many[:40], 41000)) == 39
    assert len(player.call("tickFractions", many, 41000, 100)) == 40


@pytest.mark.parametrize("pos,dur,frac", [
    (0, 1000, 0),
    (500, 1000, 0.5),
    (1000, 1000, 1),
    (2000, 1000, 1),
    (-10, 1000, 0),
    (500, 0, 0),
    (None, 1000, 0),
])
def test_fraction(player, pos, dur, frac):
    assert player.call("fraction", pos, dur) == frac


@pytest.mark.parametrize("frac,dur,pos", [
    (0, 48693108, 0),
    (0.5, 48693108, 24346554),
    (1, 48693108, 48693108),
    (1.5, 1000, 1000),
    (-0.5, 1000, 0),
    (0.3333, 1000, 333),
    (0.5, 0, 0),
    (None, 1000, 0),
])
def test_position_at(player, frac, dur, pos):
    assert player.call("positionAt", frac, dur) == pos


@pytest.mark.parametrize("pos,target,settled", [
    (100000, 100000, True),
    (101500, 100000, True),
    (98500, 100000, True),
    (101501, 100000, False),
    (8642562, 20000000, False),
    (5000, -1, True),
    (5000, None, True),
    (None, 1000, False),
])
def test_seek_settled(player, pos, target, settled):
    assert player.call("seekSettled", pos, target) == settled


@pytest.mark.parametrize("pos,target,start,settled", [
    # Seek forward 100000 → 101000: a report from before the seek is stale.
    (100100, 101000, 100000, False),
    (100499, 101000, 100000, False),
    (100500, 101000, 100000, True),
    (101000, 101000, 100000, True),
    (101800, 101000, 100000, True),
    # Seek back 200000 → 199000.
    (199900, 199000, 200000, False),
    (199100, 199000, 200000, True),
    # A long seek: the old position is never within the settle window.
    (20000000, 20000000, 8642562, True),
    (8643000, 20000000, 8642562, False),
    # Start unknown: proximity alone.
    (100100, 101000, -1, True),
    (100100, 101000, None, True),
])
def test_seek_settled_ignores_stale_reports(player, pos, target, start, settled):
    assert player.call("seekSettled", pos, target, start) == settled


def test_speed_presets(player):
    assert player.evaluate("SPEED_PRESETS") == [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
