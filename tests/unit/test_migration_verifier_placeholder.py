"""A `.verify.sql` with no assertion in it is skipped, not failed (#311).

`migrate generate` emits a placeholder sidecar, so this is the shape the
overwhelming majority of sidecars will have on the day they are created: a
comment saying what to write, and no statement.

Under 1.11.0 that file reported **`failed`**:

* `split_statements('-- write an assertion here\\n')` is `[]`, so
  `validate_verify_sql` iterates
  nothing and passes;
* `run_verify` then hands the comment text to `cursor.execute`, and
  `cursor.fetchone()` raises `psycopg.ProgrammingError` ("the last operation
  didn't produce a result");
* that is a `psycopg.Error`, so it is caught and returned as `failed` with the
  driver's message attached.

Which means "just add a `.verify.sql`" was not actually available to the
reporter either — every migration they created one for would have gone red.
Emitting placeholders without this fix would have inverted the release.

`VerifyResult.status` already declared a fourth literal, `"skipped"`, that
nothing emitted. This is what it is for.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest

from confiture.core.migration_verifier import MigrationVerifier

PLACEHOLDERS = pytest.mark.parametrize(
    "content",
    [
        pytest.param("-- assert what this migration achieved\n", id="line-comment"),
        pytest.param("/* nothing yet */\n", id="block-comment"),
        pytest.param("", id="empty"),
        pytest.param("   \n\n  \n", id="whitespace"),
    ],
)


@pytest.fixture
def conn() -> MagicMock:
    c = MagicMock()
    cur = MagicMock()
    c.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    c.cursor.return_value.__exit__ = MagicMock(return_value=False)
    c._cursor = cur
    return c


@PLACEHOLDERS
def test_a_sidecar_with_no_statement_is_skipped(
    conn: MagicMock, tmp_path: Path, content: str
) -> None:
    f = tmp_path / "20260101000000_init.verify.sql"
    f.write_text(content)

    result = MigrationVerifier(connection=conn, migrations_dir=tmp_path).run_verify(
        "20260101000000", "init", f
    )

    assert result.status == "skipped"
    assert result.error is None


@PLACEHOLDERS
def test_it_never_reaches_the_database(conn: MagicMock, tmp_path: Path, content: str) -> None:
    """No statement means no round-trip — not even a SAVEPOINT.

    Asserting on the connection rather than on the status is what makes this
    independent of how the driver happens to react to comment-only SQL.
    """
    f = tmp_path / "20260101000000_init.verify.sql"
    f.write_text(content)

    MigrationVerifier(connection=conn, migrations_dir=tmp_path).run_verify(
        "20260101000000", "init", f
    )

    conn._cursor.execute.assert_not_called()


def test_the_driver_error_this_replaces(conn: MagicMock, tmp_path: Path) -> None:
    """Pins *why* the fix is a guard rather than a wider `except`.

    With the real driver's reaction simulated, the pre-1.12.0 path produced
    `failed` plus a psycopg message. Nothing in the file warranted either.
    """
    conn._cursor.fetchone.side_effect = psycopg.ProgrammingError(
        "the last operation didn't produce a result"
    )
    f = tmp_path / "20260101000000_init.verify.sql"
    f.write_text("-- assert what this migration achieved\n")

    result = MigrationVerifier(connection=conn, migrations_dir=tmp_path).run_verify(
        "20260101000000", "init", f
    )

    assert result.status == "skipped"
    assert result.error is None


def test_a_real_assertion_is_still_executed(conn: MagicMock, tmp_path: Path) -> None:
    """The other half: a sidecar with a query must still run.

    Without this, returning `skipped` unconditionally passes everything above.
    """
    conn._cursor.fetchone.return_value = (True,)
    f = tmp_path / "20260101000000_init.verify.sql"
    f.write_text("-- check it landed\nSELECT count(*) = 0 FROM tb_widget;\n")

    result = MigrationVerifier(connection=conn, migrations_dir=tmp_path).run_verify(
        "20260101000000", "init", f
    )

    assert result.status == "verified"
    assert conn._cursor.execute.called
