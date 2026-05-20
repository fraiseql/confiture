"""Transport layer for notification hooks.

A :class:`Transport` ships a rendered :class:`TransportPayload` to its
destination.  Concrete transports:

- :class:`HttpTransport` — POSTs the payload over HTTPS via stdlib
  ``urllib.request`` with retries, configurable timeout, and TLS
  verification on by default.
- :class:`SmtpTransport` — sends the payload as an email via stdlib
  ``smtplib`` + ``email.message.EmailMessage``.  ``password`` is a
  ``pydantic.SecretStr`` and ``_login_safely`` scrubs frame locals on
  exception so the cleartext never leaks via ``show_locals``.
- :class:`StdoutTransport` — writes the payload to a text stream (default
  ``sys.stdout``).  Used by ``confiture hooks test --dry-run`` and by the
  unit-test suite for renderer snapshot comparisons.

All transports are *synchronous*.  Hooks fire sequentially under the
current ``HookRegistry``; async transports buy nothing today and would
double the dependency footprint.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any, TextIO

from pydantic import SecretStr

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Payload + retry policy — value objects shared across transports.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransportPayload:
    """A rendered payload, plus the metadata a transport needs to ship it.

    Attributes:
        body: The serialised payload — ``bytes`` for HTTP, ``str`` for
            stdout/file/SMTP body.
        content_type: MIME type for HTTP transports; ignored by stdout/file.
        headers: Additional HTTP headers (transport-dependent).
        metadata: Transport-specific extras — e.g. SMTP ``to``, ``from``,
            ``subject``.  Ignored by transports that don't recognise the
            keys.
    """

    body: bytes | str
    content_type: str = "application/json"
    headers: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetryPolicy:
    """How many attempts an HTTP transport makes before giving up.

    Attributes:
        attempts: Total attempts including the first.  ``1`` disables retry.
        backoff_seconds: Sleep between attempts.  Multiplied by 2 on each
            retry (exponential).  ``0.0`` disables backoff.
    """

    attempts: int = 1
    backoff_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Transport ABC
# ---------------------------------------------------------------------------


class Transport(ABC):
    """A pluggable sink for rendered notification payloads.

    Subclasses implement :meth:`send`, which must raise on failure so the
    caller (``NotificationHook``) can decide whether to swallow the error
    (the default — never block a migration on a notification failure).
    """

    @abstractmethod
    def send(self, payload: TransportPayload) -> None:
        """Ship *payload* to the transport's destination.

        Raises:
            Exception: On any unrecoverable failure.  HTTP transports
                exhaust their retry budget before raising; non-retryable
                failures (4xx, malformed config) raise on the first attempt.
        """


# ---------------------------------------------------------------------------
# StdoutTransport — for tests and the ``hooks test --dry-run`` CLI.
# ---------------------------------------------------------------------------


class StdoutTransport(Transport):
    """Write the payload body to a text stream.

    Args:
        stream: Where to write.  ``None`` (default) uses ``sys.stdout``.
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    def send(self, payload: TransportPayload) -> None:
        body = payload.body
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        self._stream.write(body)
        if not body.endswith("\n"):
            self._stream.write("\n")
        self._stream.flush()


# ---------------------------------------------------------------------------
# HttpTransport — stdlib urllib with retry, timeout, TLS verification.
# ---------------------------------------------------------------------------


class HttpTransportError(RuntimeError):
    """Raised when an HTTP send fails after exhausting the retry budget."""


class HttpTransport(Transport):
    """POST the payload to *url* via ``urllib.request``.

    Args:
        url: Destination URL.  Must be HTTPS in production; HTTP is allowed
            for tests but logged with a warning.
        timeout_seconds: Per-attempt socket-read timeout.  Does NOT cover
            DNS resolution — for that, the calling phase's hook timeout
            governs the wall-clock cap.
        retry: When *None*, no retries (attempts=1).  Otherwise applies on
            5xx and connection errors only; 4xx is final to avoid duplicate
            notifications on non-idempotent receivers.
        verify_tls: When *True* (default), the SSL context verifies the
            server certificate (``ssl.CERT_REQUIRED``).  ``False`` disables
            verification — only for testing.
        method: HTTP method.  Defaults to POST.

    The transport does not log payload contents — that's the renderer's
    concern.  Connection-level logs are emitted at DEBUG.
    """

    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: float = 10.0,
        retry: RetryPolicy | None = None,
        verify_tls: bool = True,
        method: str = "POST",
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.retry = retry or RetryPolicy()
        self.verify_tls = verify_tls
        self.method = method.upper()

    def send(self, payload: TransportPayload) -> None:
        last_error: Exception | None = None
        backoff = self.retry.backoff_seconds
        for attempt in range(self.retry.attempts):
            try:
                self._send_once(payload)
                return
            except _NonRetryableHttpError as exc:
                # 4xx — propagate immediately, do not retry.
                raise HttpTransportError(str(exc)) from exc
            except _RetryableHttpError as exc:
                last_error = exc
                logger.debug(
                    "HttpTransport attempt %d/%d failed: %s",
                    attempt + 1,
                    self.retry.attempts,
                    exc,
                )
            except OSError as exc:
                # Includes socket.gaierror, ConnectionRefusedError, ssl.SSLError, etc.
                last_error = exc
                logger.debug(
                    "HttpTransport attempt %d/%d connection error: %s",
                    attempt + 1,
                    self.retry.attempts,
                    exc,
                )

            if attempt < self.retry.attempts - 1 and backoff > 0:
                time.sleep(backoff)
                backoff *= 2  # exponential

        raise HttpTransportError(
            f"HTTP send to {self.url} failed after {self.retry.attempts} attempt(s): {last_error}"
        ) from last_error

    def _send_once(self, payload: TransportPayload) -> None:
        body = payload.body if isinstance(payload.body, bytes) else payload.body.encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            method=self.method,
        )
        req.add_header("Content-Type", payload.content_type)
        for k, v in payload.headers.items():
            req.add_header(k, v)

        ctx = ssl.create_default_context()
        if not self.verify_tls:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds, context=ctx) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
        except urllib.error.HTTPError as exc:
            status = exc.code
            if 500 <= status < 600:
                raise _RetryableHttpError(f"HTTP {status} from {self.url}") from exc
            raise _NonRetryableHttpError(f"HTTP {status} from {self.url}") from exc

        if 200 <= status < 300:
            return
        if 500 <= status < 600:
            raise _RetryableHttpError(f"HTTP {status} from {self.url}")
        raise _NonRetryableHttpError(f"HTTP {status} from {self.url}")


# ---------------------------------------------------------------------------
# Internal sentinel exceptions to drive retry classification.
# ---------------------------------------------------------------------------


class _RetryableHttpError(RuntimeError):
    """5xx response — caller may retry."""


class _NonRetryableHttpError(RuntimeError):
    """4xx response — caller must not retry (duplicate-notification risk)."""


# ---------------------------------------------------------------------------
# SmtpTransport — stdlib smtplib with SecretStr password and traceback scrubbing.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SmtpConfig:
    """SMTP credentials and connection knobs.

    ``password`` is a :class:`pydantic.SecretStr`, so ``repr(cfg)``,
    ``str(cfg)``, and ``model_dump()`` on parent models all redact the
    value.  Additionally :func:`_login_safely` scrubs frame locals on
    exception so a cleartext password cannot leak via
    ``rich.traceback(show_locals=True)`` or similar tooling.
    """

    host: str
    port: int = 587
    username: str = ""
    password: SecretStr = SecretStr("")
    use_tls: bool = True
    timeout_seconds: float = 10.0


def _login_safely(server: smtplib.SMTP, cfg: SmtpConfig) -> None:
    """Call ``server.login`` while scrubbing the cleartext password from
    every frame's locals on exception.

    Without scrubbing, ``smtplib.SMTP.login(user, password)`` puts the
    cleartext in ``tb_frame.f_locals``.  Tools that walk frame locals
    (Sentry's default, ``loguru.opt(exception=True)``,
    ``rich.traceback(show_locals=True)``) will then surface the password
    in their output.  ``SecretStr`` only protects ``repr()`` / ``str()``;
    it does NOT mask f_locals.
    """
    if not cfg.username:
        return
    try:
        server.login(cfg.username, cfg.password.get_secret_value())
    except Exception as exc:
        _scrub_password_from_traceback(exc.__traceback__, cfg.password.get_secret_value())
        raise


def _scrub_password_from_traceback(tb, password: str) -> None:  # noqa: ANN001
    """Truncate *tb* at the first frame whose locals contain *password*.

    ``f_locals`` mutation is unreliable on function frames in CPython 3.11+
    (``PyFrame_LocalsToFast`` doesn't round-trip for fastlocals in all
    cases).  Truncation is the robust alternative: drop every frame from
    the leak site downward, so traceback-rendering tools never see the
    password-bearing frame.

    ``tb_next`` is settable on traceback objects since PEP 569 (Python 3.7).
    """
    prev = None
    cur = tb
    while cur is not None:
        if _frame_locals_contain(cur.tb_frame, password):
            # First leaky frame found.  Cut it (and everything below) off.
            if prev is not None:
                prev.tb_next = None
            else:
                # The root tb itself is leaky.  We can't replace *tb* from
                # here, but we can clear its tb_next so at least the chain
                # below it is gone.  The caller's `raise` is expected to
                # use ``from None`` in that case.
                cur.tb_next = None
            return
        prev = cur
        cur = cur.tb_next


def _frame_locals_contain(frame, password: str) -> bool:  # noqa: ANN001
    """Return True if *frame*'s locals or any of its argument-bound names
    contain the cleartext *password* as a str value."""
    try:
        locals_view = frame.f_locals
    except Exception:
        return False
    return any(isinstance(value, str) and value == password for value in locals_view.values())


class SmtpTransport(Transport):
    """Send the payload as an email via stdlib ``smtplib``.

    The renderer (typically :class:`EmailRenderer`) puts the SMTP-specific
    headers on ``TransportPayload.metadata``:

    - ``from`` (str): envelope From / ``From:`` header.
    - ``to`` (list[str] | str): recipient list.
    - ``subject`` (str): ``Subject:`` header.
    - ``cc`` (list[str], optional): Cc list.

    The body uses ``payload.content_type`` (e.g. ``text/plain`` or
    ``text/html``).

    Args:
        config: SMTP connection + credentials.
    """

    def __init__(self, config: SmtpConfig) -> None:
        self.config = config

    def send(self, payload: TransportPayload) -> None:
        meta = payload.metadata
        if "from" not in meta or "to" not in meta or "subject" not in meta:
            raise ValueError(
                "SmtpTransport requires payload.metadata with keys "
                "'from' (str), 'to' (str|list[str]), 'subject' (str)"
            )
        msg = EmailMessage()
        msg["From"] = str(meta["from"])
        recipients = meta["to"]
        if isinstance(recipients, str):
            recipients = [recipients]
        msg["To"] = ", ".join(recipients)
        if meta.get("cc"):
            cc_recipients = meta["cc"]
            if isinstance(cc_recipients, str):
                cc_recipients = [cc_recipients]
            msg["Cc"] = ", ".join(cc_recipients)
            recipients = list(recipients) + list(cc_recipients)
        msg["Subject"] = str(meta["subject"])

        body = payload.body
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        # ``text/html`` body uses set_content with subtype "html".
        if payload.content_type == "text/html":
            msg.set_content("HTML email — view in an HTML-capable client.")
            msg.add_alternative(body, subtype="html")
        else:
            msg.set_content(body)

        cfg = self.config
        try:
            with smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout_seconds) as server:
                if cfg.use_tls:
                    server.starttls(context=ssl.create_default_context())
                _login_safely(server, cfg)
                server.send_message(msg, to_addrs=recipients)
        except smtplib.SMTPAuthenticationError as exc:
            _scrub_password_from_traceback(exc.__traceback__, cfg.password.get_secret_value())
            raise
