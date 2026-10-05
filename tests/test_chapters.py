"""Chapter parsing and the ffmetadata file (ARCHITECTURE 4.3 step 5).

Audible's ``chapters.json`` is the content-metadata response: the list lives at
``content_metadata.chapter_info.chapters`` and may be flat or a tree. Only the
flat list (or the leaves of a tree) matches what the phone shows.
"""

from __future__ import annotations

from omarchy_audible.chapters import Chapter, build_ffmetadata, parse_chapters

FLAT = {
    "content_metadata": {
        "chapter_info": {
            "chapter_titles_type": "Flat",
            "chapters": [
                {"title": "One", "start_offset_ms": 0, "length_ms": 1000},
                {"title": "Two", "start_offset_ms": 1000, "length_ms": 1500},
            ],
        }
    }
}

TREE = {
    "content_metadata": {
        "chapter_info": {
            "chapter_titles_type": "Tree",
            "chapters": [
                {
                    "title": "Part I",
                    "start_offset_ms": 0,
                    "length_ms": 3000,
                    "chapters": [
                        {"title": "One", "start_offset_ms": 0, "length_ms": 1000},
                        {"title": "Two", "start_offset_ms": 1000, "length_ms": 2000},
                    ],
                },
                {
                    "title": "Part II",
                    "start_offset_ms": 3000,
                    "length_ms": 1000,
                    "chapters": [
                        {"title": "Three", "start_offset_ms": 3000, "length_ms": 1000},
                    ],
                },
            ],
        }
    }
}


def test_parse_flat_list_reads_titles_and_offsets():
    chapters = parse_chapters(FLAT)
    assert [c.title for c in chapters] == ["One", "Two"]
    assert chapters[0] == Chapter("One", 0, 1000)
    assert chapters[1].start_ms == 1000
    assert chapters[1].end_ms == 2500


def test_parse_tree_flattens_to_leaves():
    chapters = parse_chapters(TREE)
    assert [c.title for c in chapters] == ["One", "Two", "Three"]
    assert [(c.start_ms, c.length_ms) for c in chapters] == [
        (0, 1000),
        (1000, 2000),
        (3000, 1000),
    ]


def test_parse_fills_missing_offsets_sequentially():
    data = {
        "chapters": [
            {"title": "A", "length_ms": 500},
            {"title": "B", "length_ms": 700},
        ]
    }
    chapters = parse_chapters(data)
    assert [(c.start_ms, c.end_ms) for c in chapters] == [(0, 500), (500, 1200)]


def test_parse_unknown_shape_is_empty():
    assert parse_chapters({"nothing": 1}) == []
    assert parse_chapters(None) == []
    assert parse_chapters([]) == []


def test_build_ffmetadata_emits_every_chapter():
    text = build_ffmetadata([Chapter("One", 0, 1000), Chapter("Two", 1000, 2000)])
    assert text.startswith(";FFMETADATA1")
    assert text.count("[CHAPTER]") == 2
    assert "START=0" in text
    assert "END=1000" in text
    assert "START=1000" in text
    assert "END=3000" in text
    assert "title=Two" in text
