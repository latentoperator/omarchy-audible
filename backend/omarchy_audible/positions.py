"""The remote position cache (ARCHITECTURE 4.6, 4.8).

``sync`` reads the account's last positions for every catalog ASIN and caches
them in ``remote.json``; ``position-get`` (B6) refreshes the same file. The file
is the bare mapping documented in ARCHITECTURE 3 — ``{asin: {ms, updated_at}}``
— with ``updated_at`` null when the account has no position for the book, so the
newest-wins merge always resolves to the local position. ``state.json`` is never
touched here; it belongs to ``Service.qml``.

The read endpoint is ``GET 1.0/annotations/lastpositions`` (SPIKE-RESULTS S3),
whose response key is ``asin_last_position_heard_annots``. The API allows **at
most 25 ASINs per call**, so :func:`batches` chunks the request.

Nothing in this module writes to the account: the only mutating call,
``PUT 1.0/lastpositions/``, lands with B6's ``position-push``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from . import fsutil, protocol
from .errors import PipelineError
from .log import log

LASTPOSITIONS_ENDPOINT = "1.0/annotations/lastpositions"
POSITION_BATCH_SIZE = 25


def empty_entry() -> dict[str, Any]:
    """The cache entry for a book with no position on the account."""
    return {"ms": 0, "updated_at": None}


def batches(
    asins: Sequence[str], size: int = POSITION_BATCH_SIZE
) -> list[list[str]]:
    """Chunk ``asins`` (deduplicated, order kept) into calls of at most ``size``."""
    unique = list(dict.fromkeys(asins))
    return [unique[start : start + size] for start in range(0, len(unique), size)]


def _entry(last_position_heard: Any) -> dict[str, Any]:
    if not isinstance(last_position_heard, dict):
        return empty_entry()
    if last_position_heard.get("status") != "Exists":
        return empty_entry()
    ms = last_position_heard.get("position_ms")
    if not isinstance(ms, (int, float)) or isinstance(ms, bool):
        return empty_entry()
    updated = last_position_heard.get("last_updated")
    return {
        "ms": max(0, int(ms)),
        "updated_at": updated if isinstance(updated, str) and updated else None,
    }


def parse_lastpositions(
    payload: Any, asins: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Map a ``lastpositions`` response onto one entry per requested ASIN."""
    heard: dict[str, dict[str, Any]] = {}
    annots = (
        payload.get("asin_last_position_heard_annots")
        if isinstance(payload, dict)
        else None
    )
    for annot in annots or []:
        if not isinstance(annot, dict):
            continue
        asin = annot.get("asin")
        if isinstance(asin, str) and asin:
            heard[asin] = _entry(annot.get("last_position_heard"))
    return {asin: heard.get(asin, empty_entry()) for asin in asins}


class PositionsPort(Protocol):
    """One ``lastpositions`` call, already batched by the caller."""

    def fetch_batch(self, asins: Sequence[str]) -> dict[str, dict[str, Any]]: ...


class FakePositions:
    """Fake mode has no account, so every book reports "no position"."""

    def fetch_batch(self, asins: Sequence[str]) -> dict[str, dict[str, Any]]:
        return {asin: empty_entry() for asin in asins}


class RealPositions:
    """``PositionsPort`` over an authenticated ``audible.Client``."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def fetch_batch(self, asins: Sequence[str]) -> dict[str, dict[str, Any]]:
        payload = self._client.get(LASTPOSITIONS_ENDPOINT, asins=",".join(asins))
        return parse_lastpositions(payload, asins)


def fetch_positions(
    asins: Sequence[str], port: PositionsPort
) -> dict[str, dict[str, Any]]:
    """Read every ASIN's position in batches of at most 25 (ARCHITECTURE 4.6)."""
    unique = list(dict.fromkeys(asins))
    collected: dict[str, dict[str, Any]] = {}
    for batch in batches(unique):
        try:
            collected.update(port.fetch_batch(batch))
        except PipelineError:
            raise
        except Exception as exc:  # any library failure is a read failure
            log(f"reading remote positions failed: {type(exc).__name__}")
            raise PipelineError(
                protocol.ErrorCode.NETWORK,
                "could not read the remote positions",
                hint="check the network and retry",
            ) from exc
    return {asin: collected.get(asin, empty_entry()) for asin in unique}


def write_remote(path: Path, items: dict[str, dict[str, Any]]) -> None:
    """Write ``remote.json`` atomically (ARCHITECTURE 3, 4.8)."""
    payload = {
        asin: {"ms": int(entry["ms"]), "updated_at": entry.get("updated_at")}
        for asin, entry in items.items()
    }
    fsutil.atomic_write_json(path, payload)
