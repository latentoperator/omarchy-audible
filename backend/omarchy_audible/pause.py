"""The download pause (0.1.5, ARCHITECTURE 4.2/4.3).

Audible sometimes refuses a license with ``rejectionReason:
CustomerThrottled``: downloads stop for a day or two even though the phone app
still downloads. Asking again immediately is another license request, so the
backend stops asking for a while instead. The first refusal pauses downloads
for :data:`FIRST_PAUSE_HOURS`; every further refusal without a successful
``get`` in between doubles that, up to :data:`MAX_PAUSE_HOURS`. A successful
``get`` — real or fake — removes the file, and so do ``login-finish``,
``login-import-cli`` and ``logout``, because signing in again registers a new
device.

The file lives in the mode's own data directory (``download-pause.json``), so
real and fake mode never see each other's pause, and it is written atomically.
A missing, unreadable or malformed file means "not paused": a bad file must
never block downloads for good. The clock is a parameter everywhere so the
doubling can be tested without waiting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from . import fsutil
from .paths import Paths

FIRST_PAUSE_HOURS = 4
MAX_PAUSE_HOURS = 24

# The user-facing sentence for a refusal. The drawer shows the same text
# (`qml/lib/Onboarding.js` `THROTTLED_TEXT`), and a test keeps the two in step.
THROTTLED_MESSAGE = (
    "Audible is limiting downloads for this account right now. "
    "Your books still play. Try again tomorrow."
)


@dataclass(frozen=True)
class Pause:
    """One run of throttled refusals: when it began, and when it ends."""

    since: datetime
    until: datetime
    count: int


def _now(now: float | datetime | None) -> datetime:
    """The clock, as an aware UTC datetime.

    ``now`` may be a :class:`~datetime.datetime` (aware or naive, read as UTC)
    or epoch seconds; ``None`` means the real clock.
    """
    if now is None:
        return datetime.now(tz=UTC)
    if isinstance(now, datetime):
        return now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return datetime.fromtimestamp(float(now), tz=UTC)


def _parse(value: object) -> datetime | None:
    """An ISO-8601 timestamp from the file, or ``None`` when unusable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def iso(moment: datetime) -> str:
    """``moment`` as UTC ISO-8601 with seconds precision and a ``Z``."""
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def hours_for(count: int) -> int:
    """The pause length for a run of ``count`` refusals: 4, 8, 16, 24, 24 …"""
    hours = FIRST_PAUSE_HOURS * (2 ** (max(1, count) - 1))
    return min(hours, MAX_PAUSE_HOURS)


def read(paths: Paths) -> Pause | None:
    """The pause in the file, expired or not; ``None`` when there is none.

    An expired pause is still returned, so the next refusal keeps counting the
    run of refusals (and so its ``since``). Use :func:`paused` for "may
    downloads run now".
    """
    try:
        data = json.loads(paths.download_pause_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    until = _parse(data.get("until"))
    if until is None:
        return None
    count = data.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        count = 1
    return Pause(since=_parse(data.get("since")) or until, until=until, count=count)


def paused(paths: Paths, *, now: float | datetime | None = None) -> Pause | None:
    """The pause that is still in force, or ``None`` when downloads may run."""
    pause = read(paths)
    if pause is None or pause.until <= _now(now):
        return None
    return pause


def until_iso(paths: Paths, *, now: float | datetime | None = None) -> str | None:
    """``status.downloads_paused_until``: the resume time, or ``None``."""
    pause = paused(paths, now=now)
    return iso(pause.until) if pause is not None else None


def record_refusal(paths: Paths, *, now: float | datetime | None = None) -> Pause:
    """Write or extend the pause after a throttled refusal; return it.

    The first refusal pauses for four hours; each further one — nothing
    successful in between, which is what clearing the file means — doubles the
    last pause, capped at a day. ``since`` stays at the start of the run.
    """
    moment = _now(now)
    previous = read(paths)
    count = (previous.count if previous is not None else 0) + 1
    pause = Pause(
        since=previous.since if previous is not None else moment,
        until=moment + timedelta(hours=hours_for(count)),
        count=count,
    )
    fsutil.atomic_write_json(
        paths.download_pause_file,
        {"until": iso(pause.until), "since": iso(pause.since), "count": pause.count},
    )
    return pause


def clear(paths: Paths) -> None:
    """Remove the pause: a successful ``get``, or signing in again."""
    try:
        paths.download_pause_file.unlink()
    except OSError:  # no pause to clear
        pass
