"""Unit tests for core DSN credential helpers.

`redact_url` scrubs passwords for log/error output; `split_password` +
`libpq_env` keep the password off a subprocess argv (visible in `ps aux`) by
moving it into the `PGPASSWORD` environment variable.
"""

from __future__ import annotations

from confiture.core.url_redaction import libpq_env, redact_url, split_password


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
