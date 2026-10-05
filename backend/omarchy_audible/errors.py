"""Errors that map onto protocol ``error`` codes (ARCHITECTURE 4.2).

A :class:`PipelineError` is a failure the command layer turns into a single
terminal ``error`` event; it never escapes to the top-level guard. ``Cancelled``
is raised from the ``get`` SIGTERM handler so cleanup runs on the way out
(ARCHITECTURE 4.8).
"""

from __future__ import annotations


class PipelineError(Exception):
    """A download/removal failure with a stable protocol error code."""

    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


class Cancelled(Exception):
    """Raised when a running ``get`` receives SIGTERM (ARCHITECTURE 4.8)."""
