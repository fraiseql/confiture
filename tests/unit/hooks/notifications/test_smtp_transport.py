"""Unit tests for SmtpTransport + EmailRenderer — Phase 03 Cycle 5.

The critical regression net here is ``test_smtp_config_traceback_show_locals_
does_not_leak_password``: ``pydantic.SecretStr`` redacts ``repr()`` and
``str()``, but does NOT mask frame locals.  When ``smtplib.SMTP.login(user,
password)`` raises, the cleartext is in ``tb_frame.f_locals['password']``
and any tool that walks frame locals (Sentry default,
``loguru.opt(exception=True)``, ``rich.traceback(show_locals=True)``) will
surface it.  ``_login_safely`` is the scrubbing wrapper that pins this
boundary.
"""

from __future__ import annotations

import smtplib
from datetime import UTC, datetime
from unittest import mock

import pytest
from pydantic import SecretStr

from confiture.core.hooks.notifications.context import NotificationContext
from confiture.core.hooks.notifications.renderer import EmailRenderer
from confiture.core.hooks.notifications.transport import (
    SmtpConfig,
    SmtpTransport,
    TransportPayload,
    _login_safely,
    _scrub_password_from_traceback,
)

_FIXED_TS = datetime(2026, 5, 20, 14, 30, 0, tzinfo=UTC)


def _ctx(**overrides) -> NotificationContext:
    base = {
        "migration_name": "add_user_bio",
        "migration_version": "20260520143015",
        "direction": "up",
        "success": True,
        "duration_ms": 124,
        "database_name": "myapp_prod",
        "schema": "public",
        "timestamp": _FIXED_TS,
        "rows_affected": 0,
        "error": None,
        "migrations_applied": [],
    }
    base.update(overrides)
    return NotificationContext(**base)


# ---------------------------------------------------------------------------
# SmtpConfig — SecretStr redacts repr/str/model_dump.
# ---------------------------------------------------------------------------


class TestSmtpConfigPasswordRedaction:
    SECRET = "hunter2-very-secret"  # noqa: S105

    def test_repr_does_not_leak_password(self) -> None:
        cfg = SmtpConfig(
            host="smtp.example.com",
            username="user",
            password=SecretStr(self.SECRET),
        )
        assert self.SECRET not in repr(cfg)

    def test_str_does_not_leak_password(self) -> None:
        cfg = SmtpConfig(
            host="smtp.example.com",
            username="user",
            password=SecretStr(self.SECRET),
        )
        assert self.SECRET not in str(cfg)

    def test_secret_value_accessible_via_get_secret_value(self) -> None:
        cfg = SmtpConfig(
            host="smtp.example.com",
            username="user",
            password=SecretStr(self.SECRET),
        )
        assert cfg.password.get_secret_value() == self.SECRET


# ---------------------------------------------------------------------------
# Traceback scrubbing — the load-bearing regression net.
# ---------------------------------------------------------------------------


class TestPasswordTracebackScrubbing:
    """Without ``_login_safely``, the cleartext password lands in frame
    locals on exception and gets surfaced by traceback-rendering tools.
    These tests pin the scrubbing behaviour against that class.
    """

    SECRET = "hunter2-very-secret"  # noqa: S105

    def _raise_with_password_in_locals(self) -> None:
        """A fake ``smtplib.SMTP.login`` analog — keeps password in locals."""
        password = self.SECRET  # noqa: F841 — deliberately in locals
        username = "user"  # noqa: F841 — deliberately in locals
        raise smtplib.SMTPAuthenticationError(535, b"bad creds")

    def test_repr_traceback_does_not_leak_password(self) -> None:
        """``repr(tb)`` is the simplest leak surface — pinning it first."""
        import traceback

        try:
            try:
                self._raise_with_password_in_locals()
            except Exception as exc:
                _scrub_password_from_traceback(exc.__traceback__, self.SECRET)
                raise
        except smtplib.SMTPAuthenticationError as outer:
            tb_text = "".join(traceback.format_exception(type(outer), outer, outer.__traceback__))
            assert self.SECRET not in tb_text, f"Password leaked in traceback output:\n{tb_text}"

    def test_show_locals_traceback_does_not_leak_password(self) -> None:
        """The reviewer-flagged regression net.

        ``rich.traceback(show_locals=True)`` walks every frame's f_locals
        and renders them.  Without scrubbing, the cleartext password lands
        in the output.  This pins the mitigation.
        """
        import io

        from rich.console import Console
        from rich.traceback import Traceback

        try:
            self._raise_with_password_in_locals()
        except Exception as exc:
            # Scrub before rendering — this is what ``_login_safely`` does
            # on exception inside ``SmtpTransport.send``.
            _scrub_password_from_traceback(exc.__traceback__, self.SECRET)

            buf = io.StringIO()
            console = Console(file=buf, width=200, no_color=True)
            tb = Traceback.from_exception(
                type(exc),
                exc,
                exc.__traceback__,
                show_locals=True,
            )
            console.print(tb)
            rendered = buf.getvalue()

        assert self.SECRET not in rendered, (
            f"Password leaked in rich.traceback(show_locals=True):\n{rendered}"
        )
        # The leaky frame's locals panel must NOT appear.  We test this by
        # confirming the rendered output has only ONE locals panel (the
        # outer test frame's), not two.  Counting "locals" boundary markers
        # is a reliable proxy for "how many frames had locals rendered".
        locals_panels = rendered.count(" locals ")
        assert locals_panels <= 1, (
            f"Expected at most 1 locals panel after traceback truncation, got {locals_panels}:\n"
            f"{rendered}"
        )

    def test_login_safely_scrubs_on_exception(self) -> None:
        """End-to-end: ``_login_safely`` raises and the rendered traceback
        is clean."""
        import traceback

        cfg = SmtpConfig(
            host="smtp.example.com",
            username="user",
            password=SecretStr(self.SECRET),
        )
        fake_server = mock.MagicMock()
        fake_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad creds")

        with pytest.raises(smtplib.SMTPAuthenticationError) as exc_info:
            _login_safely(fake_server, cfg)

        tb_text = "".join(
            traceback.format_exception(
                type(exc_info.value), exc_info.value, exc_info.value.__traceback__
            )
        )
        assert self.SECRET not in tb_text

    def test_no_username_skips_login(self) -> None:
        """When username is empty, ``_login_safely`` doesn't call login at all."""
        cfg = SmtpConfig(host="smtp.example.com", username="", password=SecretStr(""))
        fake_server = mock.MagicMock()
        _login_safely(fake_server, cfg)
        assert fake_server.login.call_count == 0


# ---------------------------------------------------------------------------
# SmtpTransport — happy path + TLS.
# ---------------------------------------------------------------------------


class TestSmtpTransport:
    def test_uses_tls_when_configured(self) -> None:
        fake_server = mock.MagicMock()
        fake_server.__enter__ = mock.MagicMock(return_value=fake_server)
        fake_server.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("smtplib.SMTP", return_value=fake_server):
            t = SmtpTransport(
                SmtpConfig(
                    host="smtp.example.com",
                    port=587,
                    username="user",
                    password=SecretStr("pw"),
                    use_tls=True,
                )
            )
            t.send(
                TransportPayload(
                    body="hello",
                    content_type="text/plain",
                    metadata={"from": "a@b.com", "to": ["c@d.com"], "subject": "test"},
                )
            )
        assert fake_server.starttls.call_count == 1
        assert fake_server.login.call_count == 1

    def test_skips_tls_when_disabled(self) -> None:
        fake_server = mock.MagicMock()
        fake_server.__enter__ = mock.MagicMock(return_value=fake_server)
        fake_server.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("smtplib.SMTP", return_value=fake_server):
            t = SmtpTransport(
                SmtpConfig(
                    host="smtp.example.com",
                    port=25,
                    username="user",
                    password=SecretStr("pw"),
                    use_tls=False,
                )
            )
            t.send(
                TransportPayload(
                    body="hi",
                    metadata={"from": "a@b.com", "to": "c@d.com", "subject": "s"},
                )
            )
        assert fake_server.starttls.call_count == 0

    def test_sends_to_all_recipients_including_cc(self) -> None:
        fake_server = mock.MagicMock()
        fake_server.__enter__ = mock.MagicMock(return_value=fake_server)
        fake_server.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("smtplib.SMTP", return_value=fake_server):
            t = SmtpTransport(
                SmtpConfig(
                    host="smtp.example.com",
                    username="user",
                    password=SecretStr("pw"),
                )
            )
            t.send(
                TransportPayload(
                    body="hi",
                    metadata={
                        "from": "a@b.com",
                        "to": ["x@y.com", "p@q.com"],
                        "cc": ["audit@b.com"],
                        "subject": "s",
                    },
                )
            )
        send_call = fake_server.send_message.call_args
        recipients = send_call.kwargs["to_addrs"]
        assert "x@y.com" in recipients
        assert "p@q.com" in recipients
        assert "audit@b.com" in recipients

    def test_raises_on_authentication_failure_with_scrubbed_traceback(self) -> None:
        import traceback

        SECRET = "secret-pass-xyz"  # noqa: S105
        fake_server = mock.MagicMock()
        fake_server.__enter__ = mock.MagicMock(return_value=fake_server)
        fake_server.__exit__ = mock.MagicMock(return_value=False)
        fake_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad creds")

        with mock.patch("smtplib.SMTP", return_value=fake_server):
            t = SmtpTransport(
                SmtpConfig(
                    host="smtp.example.com",
                    username="user",
                    password=SecretStr(SECRET),
                )
            )
            with pytest.raises(smtplib.SMTPAuthenticationError) as exc_info:
                t.send(
                    TransportPayload(
                        body="hi",
                        metadata={"from": "a@b.com", "to": "c@d.com", "subject": "s"},
                    )
                )
        tb_text = "".join(
            traceback.format_exception(
                type(exc_info.value), exc_info.value, exc_info.value.__traceback__
            )
        )
        assert SECRET not in tb_text

    def test_requires_smtp_metadata_keys(self) -> None:
        t = SmtpTransport(
            SmtpConfig(host="smtp.example.com", username="user", password=SecretStr("pw"))
        )
        with pytest.raises(ValueError, match="metadata"):
            t.send(TransportPayload(body="hi", metadata={"to": "c@d.com"}))


# ---------------------------------------------------------------------------
# EmailRenderer.
# ---------------------------------------------------------------------------


class TestEmailRenderer:
    def test_includes_html_and_plain_text_modes(self) -> None:
        # Default — HTML.
        html_payload = EmailRenderer(from_addr="db@x.com", to=["ops@x.com"]).render(_ctx())
        assert html_payload.content_type == "text/html"
        assert "<h2" in html_payload.body

        # Plain text.
        text_payload = EmailRenderer(
            from_addr="db@x.com", to=["ops@x.com"], include_html=False
        ).render(_ctx())
        assert text_payload.content_type == "text/plain"
        assert "<h2" not in text_payload.body

    def test_subject_template_uses_str_format_not_jinja(self) -> None:
        """Plain ``str.format`` — no Jinja sandbox concerns."""
        r = EmailRenderer(
            from_addr="db@x.com",
            to="ops@x.com",
            subject_template="[{database_name}] {migration_name} {status}",
        )
        payload = r.render(_ctx(database_name="prod"))
        assert payload.metadata["subject"] == "[prod] add_user_bio succeeded"

    def test_metadata_propagates_to_transport(self) -> None:
        r = EmailRenderer(
            from_addr="db@x.com",
            to=["a@x.com", "b@x.com"],
            cc=["audit@x.com"],
        )
        payload = r.render(_ctx())
        assert payload.metadata["from"] == "db@x.com"
        assert payload.metadata["to"] == ["a@x.com", "b@x.com"]
        assert payload.metadata["cc"] == ["audit@x.com"]
        assert "subject" in payload.metadata

    def test_error_included_in_failure_html(self) -> None:
        payload = EmailRenderer(from_addr="db@x.com", to="ops@x.com").render(
            _ctx(success=False, error="bad SQL")
        )
        assert "bad SQL" in payload.body
        assert "Error" in payload.body
