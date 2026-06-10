"""Connection-URL credential redaction (core-side, import-safe).

Lives in ``core`` so that ``core`` modules — the ``psql`` applier, the
schema-artifact and restore paths — can scrub DSN passwords out of error messages
and logs without importing from :mod:`confiture.cli` (``core`` must never depend
on ``cli``). :mod:`confiture.cli.helpers` re-exports :func:`redact_url` from here
for backwards compatibility.
"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def redact_url(url: str) -> str:
    """Return *url* with any password replaced by ``***`` (username preserved).

    Use before emitting a connection URL into JSON output, logs, or error
    messages so DSN credentials never leak to stdout / CI artifacts.

    Args:
        url: A connection URL that may embed a password.

    Returns:
        The URL with its password redacted (unchanged if there is none).
    """
    parsed = urlparse(url)
    if not parsed.password:
        return url
    host_part = parsed.hostname or ""
    if parsed.port:
        host_part = f"{host_part}:{parsed.port}"
    if parsed.username:
        host_part = f"{parsed.username}:***@{host_part}"
    return urlunparse(parsed._replace(netloc=host_part))
