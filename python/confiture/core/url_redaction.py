"""DSN credential helpers (core-side, import-safe).

Two concerns, one home:

- :func:`redact_url` scrubs a password to ``***`` for safe **log / error** output.
- :func:`split_password` + :func:`libpq_env` keep a password off a **subprocess
  argv** — a DSN passed as ``-d <url>`` is visible in the process list (``ps
  aux``), so the password is moved into the ``PGPASSWORD`` environment variable
  instead.

Lives in ``core`` so that ``core`` modules — the ``psql`` applier and the
``pg_dump`` paths — can use them without importing from :mod:`confiture.cli`
(``core`` must never depend on ``cli``). :mod:`confiture.cli.helpers` re-exports
:func:`redact_url` from here for backwards compatibility.
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlparse, urlunparse


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


def split_password(url: str) -> tuple[str, str | None]:
    """Return *url* with its password removed, plus the password (or None).

    Move a DSN password out of the URL so it can be passed to a subprocess via
    ``PGPASSWORD`` rather than on argv (where it shows in ``ps aux``). The
    returned password is **percent-decoded** to its literal value, because
    ``PGPASSWORD`` is used verbatim by libpq whereas a password inside a URI is
    percent-decoded by libpq. The username component is preserved exactly (still
    percent-encoded) so the sanitised URL stays a valid URI.

    Args:
        url: A connection URL that may embed a password.

    Returns:
        ``(url_without_password, password)``; ``(url, None)`` when there is none.
    """
    parsed = urlparse(url)
    if not parsed.password:
        return url, None
    password = unquote(parsed.password)
    host_part = parsed.hostname or ""
    if parsed.port:
        host_part = f"{host_part}:{parsed.port}"
    if parsed.username:
        host_part = f"{parsed.username}@{host_part}"
    return urlunparse(parsed._replace(netloc=host_part)), password


def libpq_env(password: str | None, *, extra_options: str | None = None) -> dict[str, str]:
    """Build a subprocess environment for a libpq client (``psql`` / ``pg_dump``).

    Copies the current environment (so ``PATH`` and any other ``PG*`` vars carry
    through), optionally injecting ``PGPASSWORD`` (so the password never appears
    on argv) and appending ``extra_options`` to ``PGOPTIONS`` (preserving any
    value already set).

    Args:
        password: Password to expose via ``PGPASSWORD``, or None to omit it.
        extra_options: ``-c key=value`` fragment to append to ``PGOPTIONS``.

    Returns:
        A new environment dict suitable for ``subprocess.run(..., env=...)``.
    """
    env = os.environ.copy()
    if password is not None:
        env["PGPASSWORD"] = password
    if extra_options:
        existing = env.get("PGOPTIONS", "")
        env["PGOPTIONS"] = f"{existing} {extra_options}".strip()
    return env
