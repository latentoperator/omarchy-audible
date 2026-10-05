"""Audible chapter lists and the ffmetadata file ffmpeg applies.

Chapters come from Audible's list, not from the audio file (G0 decision): one
book carried 20 embedded chapters against 46 from the API. audible-cli
``--chapter`` writes the content-metadata response to ``<ASIN>-chapters.json``;
the list lives at ``content_metadata.chapter_info.chapters`` and can be flat or a
tree. Only leaves carry audio, so a tree is flattened to its leaves, which
matches the ``Flat`` count (SPIKE-RESULTS S2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Chapter:
    """One chapter, in milliseconds, as ffmpeg's ffmetadata wants it."""

    title: str
    start_ms: int
    length_ms: int

    @property
    def end_ms(self) -> int:
        return self.start_ms + self.length_ms


def _find_nodes(data: Any) -> list[dict[str, Any]] | None:
    """Locate the raw chapter node list inside a chapters.json document."""
    if isinstance(data, list):
        return [node for node in data if isinstance(node, dict)]
    if isinstance(data, dict):
        chapters = data.get("chapters")
        if isinstance(chapters, list):
            return [node for node in chapters if isinstance(node, dict)]
        for key in ("chapter_info", "content_metadata"):
            if key in data:
                found = _find_nodes(data[key])
                if found is not None:
                    return found
    return None


def _flatten(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Depth-first leaves only: a section header owns no audio of its own."""
    leaves: list[dict[str, Any]] = []
    for node in nodes:
        children = node.get("chapters")
        if isinstance(children, list) and children:
            leaves.extend(_flatten([c for c in children if isinstance(c, dict)]))
        else:
            leaves.append(node)
    return leaves


def _length_ms(node: dict[str, Any]) -> int:
    length = node.get("length_ms")
    if isinstance(length, (int, float)) and length > 0:
        return round(length)
    seconds = node.get("length_sec")
    if isinstance(seconds, (int, float)) and seconds > 0:
        return round(seconds * 1000)
    return 0


def parse_chapters(data: Any) -> list[Chapter]:
    """Return the ordered chapter list, flattened and with start offsets filled.

    Returns an empty list for an unrecognised or absent shape; the caller then
    keeps the chapters embedded in the audio file (ARCHITECTURE 4.3 step 5).
    """
    nodes = _find_nodes(data)
    if not nodes:
        return []
    chapters: list[Chapter] = []
    cursor = 0
    for index, node in enumerate(_flatten(nodes)):
        length = _length_ms(node)
        if length <= 0:
            continue
        start = node.get("start_offset_ms")
        if not isinstance(start, int) or start < 0:
            start = cursor
        title = str(node.get("title") or f"Chapter {index + 1}")
        chapters.append(Chapter(title=title, start_ms=start, length_ms=length))
        cursor = start + length
    return chapters


_ESCAPE_CHARS = ("\\", "=", ";", "#", "\n", "\r")


def _escape(value: str) -> str:
    for char in _ESCAPE_CHARS:
        value = value.replace(char, "\\" + ("n" if char == "\n" else char))
    return value


def build_ffmetadata(chapters: list[Chapter]) -> str:
    """Render chapters as an ffmetadata file for ``-map_chapters``."""
    lines = [";FFMETADATA1"]
    for chapter in chapters:
        lines.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={chapter.start_ms}",
                f"END={chapter.end_ms}",
                f"title={_escape(chapter.title)}",
            ]
        )
    return "\n".join(lines) + "\n"
