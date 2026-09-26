"""DSN credential helpers (core-side, import-safe).

Two concerns, one home:

- :func:`redact_url` scrubs a password to ``***`` for safe **log / error** output —
  and, for a URL that is itself the credential (a webhook), everything after the
  host.
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
import re
from urllib.parse import ParseResult, unquote, urlparse, urlunparse

_PASSWORD_KEY = "password"

#: A URI's ``scheme://user:password@``, read the way libpq reads it: the
#: userinfo ends at the first ``@`` or ``/``, so a password may hold ``#``,
#: ``?``, a quote or a ``:`` — which ``urlparse`` would take for a fragment, a
#: query or a port, and hand back only part of (#464).
_USERINFO = re.compile(r"^(?P<head>[A-Za-z][A-Za-z0-9+.-]*://[^:/@]*):(?P<password>[^/@]*)@")


def _without_userinfo_password(url: str) -> tuple[str, str | None]:
    """*url* with its userinfo password removed, and that password as written."""
    match = _USERINFO.match(url)
    if match is None:
        return url, None
    return f"{match.group('head')}@{url[match.end() :]}", match.group("password")


def _query_parts(query: str) -> list[tuple[str, str, bool]]:
    """Split a query string into ``(raw_part, raw_value, is_password)`` triples.

    Parts are kept verbatim (still percent-encoded) so the URL that is rebuilt
    from them stays byte-for-byte what libpq was going to read, minus the
    password. libpq accepts ``password`` as a URI query parameter as well as in
    the userinfo, so both spellings have to be handled.
    """
    if not query:
        return []
    parts: list[tuple[str, str, bool]] = []
    for part in query.split("&"):
        key, _, value = part.partition("=")
        parts.append((part, value, unquote(key) == _PASSWORD_KEY))
    return parts


def _netloc(parsed, *, password: str | None) -> str:
    """Rebuild the netloc with *password* (``None`` drops it, ``***`` masks it)."""
    host_part = parsed.hostname or ""
    if parsed.port:
        host_part = f"{host_part}:{parsed.port}"
    if parsed.username:
        user_part = parsed.username if password is None else f"{parsed.username}:{password}"
        host_part = f"{user_part}@{host_part}"
    return host_part


def redact_url(url: str, *, bearer: bool = False) -> str:
    """Return *url* with any password replaced by ``***`` (username preserved).

    Both places libpq reads a password from are masked: the userinfo
    (``user:pw@host``) and the ``?password=`` query key. Every other part of the
    URL is preserved verbatim. This is the only spelling of a DSN that may leave
    the process — use it before a URL goes into JSON output, a log line or an
    error message.

    Args:
        url: A connection URL that may embed a password.
        bearer: *url* is itself the credential — a Slack or Discord webhook
            carries its token in the path, others in the query — so the path,
            query and fragment are masked too, and the scheme and host are what
            is left to say where it points.

    Returns:
        The URL with its password(s) redacted (unchanged if there is none).
    """
    match = _USERINFO.match(url)
    if match is not None and match.group("password"):
        url = f"{match.group('head')}:***@{url[match.end() :]}"
    parsed = urlparse(url)
    if bearer:
        return _redact_bearer(url, parsed)
    parts = _query_parts(parsed.query)
    if not any(is_pw for _, _, is_pw in parts):
        return url
    query = "&".join(f"{_PASSWORD_KEY}=***" if is_pw else raw for raw, _, is_pw in parts)
    return urlunparse(parsed._replace(query=query))


def _redact_bearer(url: str, parsed: ParseResult) -> str:
    """*url* with its password and everything after its host masked."""
    masked = parsed._replace(
        netloc=_netloc(parsed, password="***") if parsed.password else parsed.netloc,
        path="/***" if parsed.path.strip("/") else parsed.path,
        params="***" if parsed.params else "",
        query="***" if parsed.query else "",
        fragment="***" if parsed.fragment else "",
    )
    return url if masked == parsed else urlunparse(masked)


def split_password(url: str) -> tuple[str, str | None]:
    """Return *url* with its password removed, plus the password (or None).

    Move a DSN password out of the URL so it can be passed to a subprocess via
    ``PGPASSWORD`` rather than on argv (where it shows in ``ps aux``). The
    returned password is **percent-decoded** to its literal value, because
    ``PGPASSWORD`` is used verbatim by libpq whereas a password inside a URI is
    percent-decoded by libpq. The username component is preserved exactly (still
    percent-encoded) so the sanitised URL stays a valid URI.

    A ``?password=`` query key is removed too; when both spellings are present
    the query key wins, as libpq applies query parameters after the userinfo.

    Args:
        url: A connection URL that may embed a password.

    Returns:
        ``(url_without_password, password)``; ``(url, None)`` when there is none.
    """
    stripped, userinfo_password = _without_userinfo_password(url)
    parsed = urlparse(stripped)
    parts = _query_parts(parsed.query)
    query_passwords = [value for _, value, is_pw in parts if is_pw]
    if not userinfo_password and not query_passwords:
        return url, None
    raw_password = query_passwords[-1] if query_passwords else userinfo_password
    if not query_passwords:
        return stripped, unquote(raw_password or "")
    query = "&".join(raw for raw, _, is_pw in parts if not is_pw)
    return urlunparse(parsed._replace(query=query)), unquote(raw_password or "")


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


#: A scheme that starts where no scheme character precedes it: without that
#: boundary every offset of a long run of them is a new start, and the scan is
#: quadratic (#464).
_SCHEME = r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]*://"
#: A URL's ``user:password@`` inside free text, read as libpq reads it — the
#: password runs to the first ``@`` or ``/``, quotes included.
_USERINFO_IN_TEXT = re.compile(rf"({_SCHEME}[^:/@\s]*):[^/@\s]*@")
#: A URL inside free text: a scheme, then everything up to whitespace or a quote.
_URL_IN_TEXT = re.compile(rf"{_SCHEME}[^\s'\"<>`]+")
#: libpq's keyword form, ``password=secret`` or ``password='with spaces'``.
_CONNINFO_PASSWORD = re.compile(r"(?i)\b(password\s*=\s*)(?:'(?:[^'\\]|\\.)*'|[^\s&]+)")


def redact_credentials_in(text: str) -> str:
    """*text* with every password it carries masked to ``***``.

    For a message that interpolates a connection string rather than being one:
    each URL in it goes through :func:`redact_url`, and a libpq keyword DSN's
    ``password=`` value is masked, quoted or not. Text with no credential comes
    back unchanged. The CLI's error boundary runs every error through this, so a
    message that names a DSN cannot print its password.
    """
    text = _USERINFO_IN_TEXT.sub(r"\1:***@", text)
    text = _URL_IN_TEXT.sub(lambda match: _redact_url_in_text(match.group(0)), text)
    return _CONNINFO_PASSWORD.sub(lambda match: f"{match.group(1)}***", text)


def _redact_url_in_text(url: str) -> str:
    """:func:`redact_url`, or the URL as it is when it cannot be parsed.

    Text quotes URLs that are not valid ones (an example with ``host:port``, a
    truncated DSN); masking must never be the thing that fails, and the userinfo
    has already been masked in the text.
    """
    try:
        return redact_url(url)
    except ValueError:
        return url
