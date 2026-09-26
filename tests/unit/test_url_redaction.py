"""Unit tests for core DSN credential helpers.

`redact_url` scrubs passwords for log/error output; `split_password` +
`libpq_env` keep the password off a subprocess argv (visible in `ps aux`) by
moving it into the `PGPASSWORD` environment variable.
"""

from __future__ import annotations

import time

import pytest

from confiture.url_redaction import (
    libpq_env,
    redact_credentials_in,
    redact_url,
    split_password,
)


class TestRedactUrl:
    def test_redacts_password_keeps_username(self) -> None:
        assert redact_url("postgresql://user:secret@host:5432/db") == (
            "postgresql://user:***@host:5432/db"
        )

    def test_no_password_unchanged(self) -> None:
        assert redact_url("postgresql://host/db") == "postgresql://host/db"


class TestSplitPassword:
    def test_no_password_returns_url_and_none(self) -> None:
        url = "postgresql://user@host:5432/db"
        assert split_password(url) == (url, None)

    def test_strips_password_and_returns_it(self) -> None:
        safe, password = split_password("postgresql://user:secret@host:5432/db")
        assert password == "secret"
        assert "secret" not in safe
        assert safe == "postgresql://user@host:5432/db"

    def test_percent_encoded_password_is_decoded(self) -> None:
        safe, password = split_password("postgresql://user:p%40ss%20word@host/db")
        # PGPASSWORD is used verbatim by libpq, so the literal value is returned.
        assert password == "p@ss word"
        assert "p%40ss" not in safe
        assert safe == "postgresql://user@host/db"

    def test_password_without_username(self) -> None:
        safe, password = split_password("postgresql://:secret@host/db")
        assert password == "secret"
        assert "secret" not in safe


class TestLibpqEnv:
    def test_none_password_sets_no_pgpassword(self) -> None:
        env = libpq_env(None)
        assert "PGPASSWORD" not in env
        # The full ambient environment is preserved (e.g. PATH).
        assert "PATH" in env

    def test_password_sets_pgpassword(self) -> None:
        env = libpq_env("secret")
        assert env["PGPASSWORD"] == "secret"

    def test_extra_options_appended_to_pgoptions(self, monkeypatch) -> None:
        monkeypatch.setenv("PGOPTIONS", "-c statement_timeout=5000")
        env = libpq_env(None, extra_options="-c synchronous_commit=off")
        assert "statement_timeout=5000" in env["PGOPTIONS"]
        assert "synchronous_commit=off" in env["PGOPTIONS"]

    def test_password_and_options_together(self) -> None:
        env = libpq_env("secret", extra_options="-c synchronous_commit=off")
        assert env["PGPASSWORD"] == "secret"
        assert "synchronous_commit=off" in env["PGOPTIONS"]


class TestRedactBearerUrl:
    """A webhook's URL is the credential: its path and query are the secret."""

    def test_the_path_and_query_are_masked_and_the_host_kept(self) -> None:
        assert redact_url(
            "https://user:pw@hooks.slack.com:443/services/T000/B000/SECRET?token=abc#frag",
            bearer=True,
        ) == ("https://user:***@hooks.slack.com:443/***?***#***")

    def test_a_url_with_nothing_after_its_host_is_unchanged(self) -> None:
        assert redact_url("https://hooks.example.com/", bearer=True) == (
            "https://hooks.example.com/"
        )

    def test_a_dsn_keeps_its_database_without_bearer(self) -> None:
        assert redact_url("postgresql://u:pw@host/db") == "postgresql://u:***@host/db"


#: Passwords libpq reads whole from a URI's userinfo — it ends the userinfo at
#: the first ``@`` or ``/`` — that ``urlparse`` splits at ``#`` or ``?``, or
#: that a quote would end a URL found in text (#464).
LIBPQ_PASSWORDS = ["Pa#ss", "p?w", "pa'ss", 'pa"ss', "p`w", "p<w>", "p&w=1", "p:w"]


class TestEveryPasswordLibpqReads:
    """Masked however it is spelled, since libpq connects with it (#464)."""

    @pytest.mark.parametrize("password", LIBPQ_PASSWORDS)
    def test_redact_url_masks_it_whole(self, password: str) -> None:
        masked = redact_url(f"postgresql://app:{password}@db.example:5432/prod?sslmode=require")

        assert masked == "postgresql://app:***@db.example:5432/prod?sslmode=require"

    @pytest.mark.parametrize("password", LIBPQ_PASSWORDS)
    def test_redact_credentials_in_masks_it_in_a_message(self, password: str) -> None:
        text = f"could not connect to postgresql://app:{password}@db.example/prod: refused"

        assert redact_credentials_in(text) == (
            "could not connect to postgresql://app:***@db.example/prod: refused"
        )

    @pytest.mark.parametrize("password", LIBPQ_PASSWORDS)
    def test_split_password_returns_it_whole(self, password: str) -> None:
        url, found = split_password(f"postgresql://app:{password}@db.example/prod")

        assert (url, found) == ("postgresql://app@db.example/prod", password)

    def test_a_port_is_not_a_password(self) -> None:
        for url in ("postgresql://db:5432/prod", "postgresql://h1:5432,h2:5433/prod?user=a@b"):
            assert redact_url(url) == url
            assert split_password(url) == (url, None)


def test_a_long_run_of_scheme_characters_is_scanned_in_linear_time() -> None:
    """No left boundary made every offset a new start: quadratic (#464)."""
    small, large = "a" * 20_000, "a" * 80_000

    def cost(text: str) -> float:
        start = time.perf_counter()
        redact_credentials_in(text)
        return time.perf_counter() - start

    assert cost(large) < max(cost(small) * 8, 0.05)
