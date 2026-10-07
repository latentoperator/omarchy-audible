"""Secret-scrubbing stderr logger.

Human-readable logs go to stderr, never stdout, and are filtered so that
credentials, tokens, activation bytes and pasted login URLs cannot leak into a
log file or a journal (ARCHITECTURE 4.2, 4.7).
"""

from __future__ import annotations

import re
import sys

# A name is secret when it ends in one of these words (optionally plural), so
# ``access_token``, ``refresh_token``, ``device_private_key``, ``adp_token``,
# ``website_cookies``, ``store_authentication_cookie``, ``audible_key`` and
# ``audible_iv`` are all covered by the suffix alone (F4). The names that do not
# end in one of them — the login code, the legacy account key, ``passwd`` and
# the mpv option that carries a key (B11) — are listed in full.
_SECRET_SUFFIXES = "token|key|secret|cookie|password|verifier|iv"
_SECRET_NAMES = (
    r"authorization_code|activation_bytes|passwd"
    r"|lavf_options|demuxer-lavf-o"
    r"|[\w.-]*(?:" + _SECRET_SUFFIXES + r")s?"
)

# The name of a secret: a whole word, or any dotted/dashed/underscored name
# ending in a secret suffix.
_SECRET_ALT = r"(?:" + _SECRET_NAMES + r")\b"

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
