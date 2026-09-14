"""Keep configured secrets out of text headed for a log, the GUI or an exception.

Library errors quote the value that upset them — ConfigParser put a rejected
password straight into its message, and then only the *tail* of it from the
character it tripped on. Matching on the whole value alone let that through, so
every chunk long enough to matter is masked, longest first.
"""

from __future__ import annotations

# Short enough to be a coincidence, long enough to be worth hiding.
_MIN_REVEALING_RUN = 6


def _revealing_runs(secret: str) -> list[str]:
    """Every substring of *secret* of at least ``_MIN_REVEALING_RUN`` chars, longest first."""
    if len(secret) < _MIN_REVEALING_RUN:
        return []
    return [
        secret[start : start + length]
        for length in range(len(secret), _MIN_REVEALING_RUN - 1, -1)
        for start in range(0, len(secret) - length + 1)
    ]


def redact(text: str, *secrets: str) -> str:
    """Return *text* with every configured secret (and any telling fragment of it) replaced by ``***``."""
    for secret in secrets:
        for run in _revealing_runs(secret or ""):
            text = text.replace(run, "***")
    return text
