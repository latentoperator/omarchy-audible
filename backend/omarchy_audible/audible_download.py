"""Run ``audible download`` for the ASIN in ``OMARCHY_AUDIBLE_ASIN``.

``get`` starts this module (``python -m omarchy_audible.audible_download
<options>``) instead of the ``audible`` script, so the ASIN never appears in a
command line: ``/proc/<pid>/cmdline`` is readable by every local user, the
environment only by the same user. The options are passed through unchanged
and ``-a <asin>`` is added in this process only. ``audible-cli`` is imported
here, inside the plugin venv, never by the rest of the backend.
"""

from __future__ import annotations

import os
import re
import sys

ASIN_ENV = "OMARCHY_AUDIBLE_ASIN"
_ASIN_RE = re.compile(r"^[A-Za-z0-9]{4,32}$")


def download_args(argv: list[str], env: dict[str, str]) -> list[str] | None:
    """The ``audible`` arguments, or ``None`` when there is no valid ASIN."""
    asin = str(env.get(ASIN_ENV, "")).strip()
    if not _ASIN_RE.match(asin):
        return None
    return ["download", "-a", asin, *argv]


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
    audible_cli.main(args=args, prog_name="audible")
    return 0  # main() exits itself


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
