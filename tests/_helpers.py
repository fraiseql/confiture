"""Small helpers shared across test layers."""

from __future__ import annotations

import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Remove ANSI colour codes (Rich forces them when ``GITHUB_ACTIONS`` is set)."""
    return _ANSI_RE.sub("", text)
