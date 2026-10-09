"""Errors that map onto protocol ``error`` codes (ARCHITECTURE 4.2).

A :class:`PipelineError` is a failure the command layer turns into a single
terminal ``error`` event; it never escapes to the top-level guard. ``Cancelled``
is raised from the ``get`` SIGTERM handler so cleanup runs on the way out
(ARCHITECTURE 4.8).
"""

from __future__ import annotations

from .protocol import ErrorCode


class PipelineError(Exception):
    """A download/removal failure with a stable protocol error code."""

    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


class Cancelled(Exception):
    """Raised when a running ``get`` receives SIGTERM (ARCHITECTURE 4.8)."""


_AUTH_ERROR_NAMES = {"Unauthorized", "NoRefreshToken", "AuthFlowError"}
_NETWORK_ERROR_NAMES = {
    "NetworkError",
    "NotResponding",
    "RatelimitError",
    "ServerError",
    "TransportError",
    "TimeoutException",
    "ConnectError",
    "OSError",
    "ConnectionError",
    "TimeoutError",
    "gaierror",
}


def classify_audible_error(exc: BaseException) -> str:
    """Map an Audible read exception to a stable protocol code by its MRO names.

    Class-name matching keeps the classifier independent of the optional
    ``audible`` and ``httpx`` packages and lets port tests use lookalike types.
    """
    names = {cls.__name__ for cls in type(exc).__mro__}
    if names & _AUTH_ERROR_NAMES:
        return ErrorCode.AUTH_FAILED
    if names & _NETWORK_ERROR_NAMES:
        return ErrorCode.NETWORK
    return ErrorCode.INTERNAL
