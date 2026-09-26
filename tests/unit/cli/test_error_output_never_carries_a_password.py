"""An error never prints a password, whoever raised it.

``migrate schema-to-schema`` put an unreachable ``--source`` DSN into its error
verbatim — ``Could not connect to 'postgresql://bob:s3cret@…'`` — in the JSON
envelope and on stderr alike. The site is fixed; the boundary every command's
errors pass through also scrubs, so the next message that interpolates a URL or
a ``password=`` conninfo cannot leak it either.
"""

from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner

from confiture.cli.error_json import fail
from confiture.cli.main import app
from confiture.exceptions import ConfigurationError
from confiture.url_redaction import redact_credentials_in

runner = CliRunner()
_SECRET = "s3cret-Pa55"
_UNREACHABLE = f"postgresql://bob:{_SECRET}@localhost:1/app"


@pytest.mark.parametrize("fmt", ["json", "text"])
def test_schema_to_schema_does_not_print_an_unreachable_dsn_password(fmt: str) -> None:
    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "setup",
            "--source",
            _UNREACHABLE,
            "--target",
            _UNREACHABLE,
            "--format",
            fmt,
        ],
    )

    assert result.exit_code != 0
    assert _SECRET not in result.output
    assert "bob:***@localhost:1" in result.output


def test_the_boundary_scrubs_message_hint_context_and_attributes(capsys) -> None:
    error = ConfigurationError(
        f"cannot reach {_UNREACHABLE}",
        resolution_hint=f"check host=db password={_SECRET} port=5432",
        context={"url": _UNREACHABLE, "nested": [f"postgres://u:{_SECRET}@h/d"]},
    )
    error.target_url = _UNREACHABLE  # a subclass-style attribute a renderer may read

    with pytest.raises(typer.Exit):
        fail(error, json_mode=True)

    out = capsys.readouterr().out
    assert _SECRET not in out
    assert "bob:***@" in out


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"x {_UNREACHABLE} y", "x postgresql://bob:***@localhost:1/app y"),
        (f"'{_UNREACHABLE}'.", "'postgresql://bob:***@localhost:1/app'."),
        (
            f"postgresql://h/db?password={_SECRET}&sslmode=require",
            "postgresql://h/db?password=***&sslmode=require",
        ),
        (f"host=db password={_SECRET} user=u", "host=db password=*** user=u"),
        (f"host=db password='{_SECRET} x' user=u", "host=db password=*** user=u"),
        ("postgresql://localhost/app and no secret", "postgresql://localhost/app and no secret"),
        (f"postgresql://u:{_SECRET}@host:port/db", "postgresql://u:***@host:port/db"),
    ],
    ids=[
        "url",
        "quoted-url",
        "query-key",
        "conninfo",
        "conninfo-quoted",
        "no-secret",
        "unparseable",
    ],
)
def test_credentials_in_free_text_are_masked(text: str, expected: str) -> None:
    assert redact_credentials_in(text) == expected


def test_a_value_printed_through_verbatim_carries_no_password() -> None:
    """``verbatim`` is how every interpolated value reaches the console (a guard enforces it)."""
    from confiture.cli.markup import verbatim

    assert (
        verbatim(f"connected to {_UNREACHABLE}")
        == "connected to postgresql://bob:***@localhost:1/app"
    )
