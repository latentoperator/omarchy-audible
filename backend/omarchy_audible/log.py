"""Secret-scrubbing stderr logger.

Human-readable logs go to stderr, never stdout, and are filtered so that
credentials, tokens, activation bytes and pasted login URLs cannot leak into a
log file or a journal (ARCHITECTURE 4.2, 4.7).
"""

from __future__ import annotations

import re
import sys

_SECRET_KEYS = (
    "authorization_code",
    "access_token",
    "refresh_token",
    "activation_bytes",
    "password",
    "passwd",
    "secret",
    "token",
    "verifier",
    "key",
    "iv",
)

_SECRET_ALT = "|".join(_SECRET_KEYS)

# ``key=value`` and ``key: value`` in plain logs and exception text.
_KEY_VALUE = re.compile(
    r"(?i)\b(" + _SECRET_ALT + r")\b(\s*[=:]\s*)([\"']?)([^\s&\"']+)"
)
# ``"key": "value"`` / ``'key': 'value'`` in JSON or dict ``repr()`` output: the
# most likely leak shape when a voucher dict reaches a log line via ``repr``.
_QUOTED_KEY_VALUE = re.compile(
    r"(?i)(?P<qk>[\"'])(?P<key>" + _SECRET_ALT + r")(?P=qk)"
    r"(?P<sep>\s*:\s*)(?P<qv>[\"'])(?P<value>.*?)(?P=qv)"
)
_BEARER = re.compile(r"(?i)\b(bearer)\s+([A-Za-z0-9._~+/\-]+=*)")
_QUERY = re.compile(
    r"(?i)([?&](?:openid\.oa2\.)?(?:authorization_code|code|access_token)=)([^&\s]+)"
)


def scrub(text: str) -> str:
    """Return ``text`` with secret values replaced by ``***``."""
    text = _QUOTED_KEY_VALUE.sub(
        lambda m: (
            f"{m.group('qk')}{m.group('key')}{m.group('qk')}{m.group('sep')}"
            f"{m.group('qv')}***{m.group('qv')}"
        ),
        text,
    )
    text = _KEY_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}***", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)} ***", text)
    text = _QUERY.sub(lambda m: f"{m.group(1)}***", text)
    return text


def log(message: str, *, level: str = "info") -> None:
    """Write a scrubbed log line to stderr."""
    sys.stderr.write(f"omarchy-audible {level}: {scrub(str(message))}\n")
    sys.stderr.flush()
