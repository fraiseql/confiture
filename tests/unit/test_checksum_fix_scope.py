"""``verify-checksums --fix`` re-stamps the mismatches, once (#311).

Two defects in the one operation whose help string calls itself "(dangerous)":

* ``update_all_checksums`` iterates **every** stored row, so ``--fix`` for a
  single bad checksum printed "Found 1 checksum mismatch(es)" and then
  "Updated 268 checksum(s)" on the reporter's install. The output was not
  describing the operation.
* ``update_checksum`` commits per row, so ``--fix`` was 268 transactions. A
  failure partway leaves the ledger half re-stamped with nothing recording
  which half.

The caller already holds the list it should act on — ``admin.py`` computes
``mismatches = verifier.verify_all(...)`` and then called
``update_all_checksums(...)``, discarding it.

``update_checksum`` keeps its single-row, commit-now contract: it is a
library method and changing its transaction semantics underneath a caller is
not this issue's business. ``update_all_checksums`` keeps working too — it is
the documented "re-stamp everything" escape hatch. Neither is what ``--fix``
calls any more.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from confiture.core.checksum import ChecksumMismatch, MigrationChecksumVerifier


def _mismatch(version: str, name: str, actual: str) -> ChecksumMismatch:
    return ChecksumMismatch(
        version=version,
        name=name,
        file_path=Path(f"db/migrations/{version}_{name}.up.sql"),
        expected="old" + version,
        actual=actual,
    )


@pytest.fixture
def conn() -> MagicMock:
    c = MagicMock()
    cur = MagicMock()
    c.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    c.cursor.return_value.__exit__ = MagicMock(return_value=False)
    c._cursor = cur
    return c


def _updated_versions(conn: MagicMock) -> list[str]:
    """The version bound to each UPDATE, in order."""
    return [
        call[0][1][1] for call in conn._cursor.execute.call_args_list if "UPDATE" in str(call[0][0])
    ]


class TestScope:
    def test_only_the_mismatched_versions_are_updated(self, conn: MagicMock) -> None:
        """One bad checksum in a ledger of three updates exactly one row."""
        verifier = MigrationChecksumVerifier(conn)

        updated = verifier.update_checksums_for([_mismatch("002", "add_email", "newsum")])

        assert updated == 1
        assert _updated_versions(conn) == ["002"]

    def test_the_new_checksum_is_the_one_already_computed(self, conn: MagicMock) -> None:
        """`verify_all` hashed the file to find the mismatch; don't hash it twice.

        `m.actual` *is* the current file's digest. Re-reading the file here
        would also open a window in which the two differ.
        """
        verifier = MigrationChecksumVerifier(conn)

        verifier.update_checksums_for([_mismatch("002", "add_email", "deadbeef")])

        assert conn._cursor.execute.call_args[0][1][0] == "deadbeef"

    def test_no_mismatches_touches_nothing(self, conn: MagicMock) -> None:
        verifier = MigrationChecksumVerifier(conn)

        assert verifier.update_checksums_for([]) == 0
        assert _updated_versions(conn) == []
        conn.commit.assert_not_called()


class TestAtomicity:
    def test_every_update_lands_in_one_transaction(self, conn: MagicMock) -> None:
        verifier = MigrationChecksumVerifier(conn)

        verifier.update_checksums_for(
            [_mismatch("001", "init", "a"), _mismatch("002", "e", "b"), _mismatch("003", "w", "c")]
        )

        assert _updated_versions(conn) == ["001", "002", "003"]
        assert conn.commit.call_count == 1, "one commit for the whole re-stamp, not one per row"

    def test_a_failure_partway_commits_nothing(self, conn: MagicMock) -> None:
        """The half-re-stamped ledger is the outcome this method exists to prevent."""
        conn._cursor.execute.side_effect = [None, RuntimeError("connection lost"), None]
        verifier = MigrationChecksumVerifier(conn)

        with pytest.raises(RuntimeError):
            verifier.update_checksums_for(
                [
                    _mismatch("001", "init", "a"),
                    _mismatch("002", "e", "b"),
                    _mismatch("003", "w", "c"),
                ]
            )

        conn.commit.assert_not_called()
