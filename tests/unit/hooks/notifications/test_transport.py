"""Unit tests for the Transport layer of the notifications package.

Cycle 1 of Phase 03 — Transport ABC, HttpTransport, StdoutTransport.
All tests run without a network or process subprocess; HttpTransport is
exercised against ``pytest-httpserver`` for happy-path / retry tests.
"""

from __future__ import annotations

import io
import socket
from unittest import mock

import pytest

from confiture.core.hooks.notifications.transport import (
    HttpTransport,
    HttpTransportError,
    RetryPolicy,
    StdoutTransport,
    Transport,
    TransportPayload,
)

# ---------------------------------------------------------------------------
# TransportPayload — dataclass shape
# ---------------------------------------------------------------------------


class TestTransportPayload:
    def test_defaults_apply(self) -> None:
        p = TransportPayload(body=b'{"x":1}')
        assert p.body == b'{"x":1}'
        assert p.content_type == "application/json"
        assert p.headers == {}
        assert p.metadata == {}

    def test_custom_content_type(self) -> None:
        p = TransportPayload(body="hello", content_type="text/plain")
        assert p.content_type == "text/plain"


# ---------------------------------------------------------------------------
# Transport ABC
# ---------------------------------------------------------------------------


class TestTransportABC:
    def test_transport_abc_requires_send_method(self) -> None:
        """Instantiating the ABC directly must fail; subclasses must implement send."""
        with pytest.raises(TypeError):
            Transport()  # type: ignore[abstract]

        class _BadTransport(Transport):
            pass

        with pytest.raises(TypeError):
            _BadTransport()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# RetryPolicy — defaults and field values
# ---------------------------------------------------------------------------


class TestRetryPolicy:
    def test_defaults_no_retry(self) -> None:
        rp = RetryPolicy()
        assert rp.attempts == 1
        assert rp.backoff_seconds == 0.0

    def test_custom_values(self) -> None:
        rp = RetryPolicy(attempts=3, backoff_seconds=2.0)
        assert rp.attempts == 3
        assert rp.backoff_seconds == 2.0


# ---------------------------------------------------------------------------
# StdoutTransport
# ---------------------------------------------------------------------------


class TestStdoutTransport:
    def test_writes_payload_to_stream(self) -> None:
        buf = io.StringIO()
        t = StdoutTransport(stream=buf)
        t.send(TransportPayload(body='{"hello":"world"}'))
        assert '{"hello":"world"}' in buf.getvalue()

    def test_writes_bytes_payload_decoded(self) -> None:
        buf = io.StringIO()
        t = StdoutTransport(stream=buf)
        t.send(TransportPayload(body=b'{"hello":"bytes"}'))
        assert '{"hello":"bytes"}' in buf.getvalue()

    def test_default_stream_is_stdout(self, capsys) -> None:
        StdoutTransport().send(TransportPayload(body="hello"))
        captured = capsys.readouterr()
        assert "hello" in captured.out


# ---------------------------------------------------------------------------
# HttpTransport — uses urllib.request, patched via mock
# ---------------------------------------------------------------------------


def _mock_response(status: int, body: bytes = b"ok") -> mock.MagicMock:
    """Build a fake context manager that urlopen returns."""
    resp = mock.MagicMock()
    resp.status = status
    resp.getcode.return_value = status
    resp.read.return_value = body
    resp.__enter__ = mock.MagicMock(return_value=resp)
    resp.__exit__ = mock.MagicMock(return_value=False)
    return resp


class TestHttpTransport:
    """HttpTransport — patches urllib.request.urlopen to avoid real network."""

    URL = "https://hooks.example.com/services/T1/B2/abc"

    def test_post_json_body_returns_on_2xx(self) -> None:
        with mock.patch("urllib.request.urlopen", return_value=_mock_response(200)):
            t = HttpTransport(url=self.URL)
            # Must not raise.
            t.send(TransportPayload(body=b'{"x":1}'))

    def test_post_passes_body_and_content_type(self) -> None:
        with mock.patch("urllib.request.urlopen", return_value=_mock_response(200)) as urlopen:
            t = HttpTransport(url=self.URL)
            t.send(TransportPayload(body=b'{"x":1}', content_type="application/json"))

        request_arg = urlopen.call_args.args[0]
        assert request_arg.data == b'{"x":1}'
        assert request_arg.get_header("Content-type") == "application/json"

    def test_post_raises_on_5xx_after_retries(self) -> None:
        # 5xx every attempt → final exception.
        with mock.patch("urllib.request.urlopen", return_value=_mock_response(503, b"boom")):
            t = HttpTransport(url=self.URL, retry=RetryPolicy(attempts=3, backoff_seconds=0.0))
            with pytest.raises(HttpTransportError, match="5..|HTTP 5"):
                t.send(TransportPayload(body=b'{"x":1}'))

    def test_retry_policy_attempts_then_gives_up(self) -> None:
        with mock.patch("urllib.request.urlopen", return_value=_mock_response(500)) as urlopen:
            t = HttpTransport(url=self.URL, retry=RetryPolicy(attempts=4, backoff_seconds=0.0))
            with pytest.raises(HttpTransportError):
                t.send(TransportPayload(body=b'{"x":1}'))
            assert urlopen.call_count == 4

    def test_http_transport_does_not_retry_on_4xx(self) -> None:
        """4xx is final — duplicate-notification safety for non-idempotent receivers."""
        with mock.patch("urllib.request.urlopen", return_value=_mock_response(404)) as urlopen:
            t = HttpTransport(url=self.URL, retry=RetryPolicy(attempts=5, backoff_seconds=0.0))
            with pytest.raises(HttpTransportError):
                t.send(TransportPayload(body=b'{"x":1}'))
            # Exactly one call — 4xx is not retried.
            assert urlopen.call_count == 1

    def test_retry_recovers_on_first_2xx(self) -> None:
        """If a 5xx is followed by a 2xx within the attempt budget, succeed."""
        responses = [_mock_response(500), _mock_response(502), _mock_response(200)]
        with mock.patch("urllib.request.urlopen", side_effect=responses) as urlopen:
            t = HttpTransport(url=self.URL, retry=RetryPolicy(attempts=5, backoff_seconds=0.0))
            t.send(TransportPayload(body=b'{"x":1}'))
        assert urlopen.call_count == 3

    def test_timeout_respects_config(self) -> None:
        with mock.patch("urllib.request.urlopen", return_value=_mock_response(200)) as urlopen:
            t = HttpTransport(url=self.URL, timeout_seconds=2.5)
            t.send(TransportPayload(body=b'{"x":1}'))
        kwargs = urlopen.call_args.kwargs
        assert kwargs["timeout"] == 2.5

    def test_tls_verification_on_by_default(self) -> None:
        """The default ssl context must verify certs.  ``verify_tls=False`` flips it."""
        with mock.patch("urllib.request.urlopen", return_value=_mock_response(200)) as urlopen:
            t = HttpTransport(url=self.URL)
            t.send(TransportPayload(body=b"{}"))
        ctx = urlopen.call_args.kwargs.get("context")
        # When verify is on, the SSL context's verify_mode is CERT_REQUIRED (=2).
        # The CLI builds its own context via ssl.create_default_context() — which
        # defaults to CERT_REQUIRED.  This guards against regression to None or CERT_NONE.
        import ssl

        assert ctx is not None
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_tls_verification_can_be_disabled(self) -> None:
        with mock.patch("urllib.request.urlopen", return_value=_mock_response(200)) as urlopen:
            t = HttpTransport(url=self.URL, verify_tls=False)
            t.send(TransportPayload(body=b"{}"))
        import ssl

        ctx = urlopen.call_args.kwargs.get("context")
        assert ctx is not None
        assert ctx.verify_mode == ssl.CERT_NONE

    def test_connection_error_is_retried(self) -> None:
        """Socket-level failures (DNS, refused) should follow the retry policy."""
        attempts = [
            socket.gaierror("dns failed"),
            socket.gaierror("dns failed"),
            _mock_response(200),
        ]
        with mock.patch("urllib.request.urlopen", side_effect=attempts) as urlopen:
            t = HttpTransport(url=self.URL, retry=RetryPolicy(attempts=5, backoff_seconds=0.0))
            t.send(TransportPayload(body=b"{}"))
        assert urlopen.call_count == 3

    def test_payload_headers_propagate(self) -> None:
        with mock.patch("urllib.request.urlopen", return_value=_mock_response(200)) as urlopen:
            t = HttpTransport(url=self.URL)
            t.send(
                TransportPayload(
                    body=b"{}",
                    headers={"X-Custom-Header": "yes"},
                )
            )
        req = urlopen.call_args.args[0]
        # urllib lowercases-then-titlecases the header name; use the public getter.
        assert req.get_header("X-custom-header") == "yes"
