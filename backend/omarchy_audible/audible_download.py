"""Run ``audible download`` for the ASIN in ``OMARCHY_AUDIBLE_ASIN``.

``get`` starts this module (``python -m omarchy_audible.audible_download
<options>``) instead of the ``audible`` script, so the ASIN never appears in a
command line: ``/proc/<pid>/cmdline`` is readable by every local user, the
environment only by the same user. The options are passed through unchanged
and ``-a <asin>`` is added in this process only. ``audible-cli`` is imported
here, inside the plugin venv, never by the rest of the backend.

It also captures the license denial reason (0.1.5, ARCHITECTURE 4.3).
audible-cli answers a refused license with ``LicenseDenied``, whose message is
the license's human text, and logs the machine-readable reason — the
``rejectionReason``, which is what separates "Audible is throttling this
account" from a real network failure — on ``audible_cli.models`` at **DEBUG**
only. Those DEBUG records never reach the console (the command line runs that
logger at INFO), so this module raises the logger to DEBUG, records the reason
codes through a filter, and drops those records again: what audible-cli prints
does not change. The reasons — never the message, the ASIN or the title — go to
``license-denied.json`` in the download's working directory, which ``get`` sets
to ``.partial/`` and deletes with it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

ASIN_ENV = "OMARCHY_AUDIBLE_ASIN"
#: The denial notes, written in the download's working directory (``.partial/``).
DENIED_FILE = "license-denied.json"

_ASIN_RE = re.compile(r"^[A-Za-z0-9]{4,32}$")

#: The logger audible-cli's license model writes to.
MODELS_LOGGER = "audible_cli.models"
#: Its DEBUG line: ``License denied message for <asin>: <message>.Reason:
#: <rejectionReason>.Type: <validationType>`` (audible-cli 0.6.0). The reason
#: is taken as it comes: a denial is a denial even when the reason is not a
#: bare code, and :data:`REASON_RE` is what decides whether it is kept.
_DENIAL_RE = re.compile(
    r"^License denied message for \S+: (?P<message>.*?)"
    r"\.Reason: (?P<reason>.*?)\.Type: \S+$"
)
#: Reason codes are Audible's; nothing else is kept, and nothing from the
#: message is written down.
REASON_RE = re.compile(r"^[A-Za-z_]{1,64}$")
#: What a throttled refusal looks like, in a reason code or in the message.
THROTTLED_RE = re.compile(r"throttl", re.IGNORECASE)


def download_args(argv: list[str], env: dict[str, str]) -> list[str] | None:
    """The ``audible`` arguments, or ``None`` when there is no valid ASIN."""
    asin = str(env.get(ASIN_ENV, "")).strip()
    if not _ASIN_RE.match(asin):
        return None
    return ["download", "-a", asin, *argv]


class LicenseDenialWatch(logging.Filter):
    """Record audible-cli's DEBUG license-denial lines and keep them off stderr.

    Attached to :data:`MODELS_LOGGER` with that logger raised to DEBUG, this
    filter is the only thing that then sees those records: returning ``False``
    stops them at the logger, before the console handler the command line
    installed would print them, so the download's stderr is what it always was.
    (The wrapper never passes ``--verbosity``, so the command line runs that
    logger at INFO and those records reached no handler before.)
    """

    def __init__(self) -> None:
        super().__init__()
        #: The ``rejectionReason`` codes seen, in order, without repeats.
        self.reasons: list[str] = []
        #: True when one of them (or its message) says the account is throttled.
        self.throttled = False
        #: True when a denied license was seen at all.
        self.denied = False
        self._level = logging.NOTSET

    def install(self) -> None:
        """Raise the models logger to DEBUG and watch it."""
        logger = logging.getLogger(MODELS_LOGGER)
        self._level = logger.level
        logger.addFilter(self)
        logger.setLevel(logging.DEBUG)

    def uninstall(self) -> None:
        """Put the models logger back the way it was found."""
        logger = logging.getLogger(MODELS_LOGGER)
        logger.removeFilter(self)
        logger.setLevel(self._level)

    def filter(self, record: logging.LogRecord) -> bool:
        """Keep one DEBUG record out of the console, recording a denial."""
        if record.levelno > logging.DEBUG:
            return True
        match = _DENIAL_RE.match(record.getMessage())
        if match is not None:
            self.denied = True
            reason = match.group("reason").strip()
            if REASON_RE.match(reason) and reason not in self.reasons:
                self.reasons.append(reason)
            if THROTTLED_RE.search(match.group("message")) or THROTTLED_RE.search(
                reason
            ):
                self.throttled = True
        return False

    def save(self, path: Path) -> None:
        """Write the denial notes to ``path``, if there was a denial."""
        if not self.denied:
            return
        payload = {"reasons": self.reasons, "throttled": self.throttled}
        try:
            path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        except OSError:  # a write we cannot make must not add a second failure
            pass


def main(argv: list[str]) -> int:
    args = download_args(argv, dict(os.environ))
    if args is None:
        sys.stderr.write(f"{ASIN_ENV} must hold one ASIN\n")
        return 2
    try:
        import audible_cli
    except ImportError:
        sys.stderr.write("audible-cli is not installed; run: omarchy-audible setup\n")
        return 2
    watch = LicenseDenialWatch()
    watch.install()
    try:
        audible_cli.main(args=args, prog_name="audible")
    finally:
        # audible-cli exits from inside its own main(); this still runs, and
        # the notes are written before the failure reaches ``get``.
        watch.uninstall()
        watch.save(Path.cwd() / DENIED_FILE)
    return 0  # main() exits itself


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
