"""The page about checksum mismatches must name the command that fixes them (#311).

`docs/reference/tracking-table.md` has a "Checksum mismatches" section — the
one page a user lands on for this question. Through 1.11.0 it told the reader
to hand-write:

    UPDATE tb_confiture
    SET checksum = encode(sha256(pg_read_binary_file('db/migrations/…')), 'hex')
    WHERE version = '…';

and never mentioned `confiture verify-checksums --fix`, which does exactly
that, scoped and atomic. A purpose-built command, routed past in favour of raw
SQL, on the page most likely to be read by someone who needs it.

The snippet was also impossible to run for many readers: `pg_read_binary_file`
is a *server-side* read, so it needs superuser and the migration file present
on the database host — not the case for any managed or remote database.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parents[3] / "docs" / "reference" / "tracking-table.md"


@pytest.fixture(scope="module")
def text() -> str:
    return DOC.read_text()


def test_the_command_is_named(text: str) -> None:
    assert "verify-checksums" in text


def test_the_read_only_check_and_the_fix_are_both_named(text: str) -> None:
    """Two questions: "does it match?" and "re-record this one". Both have answers."""
    section = text.split("## Checksum mismatches", 1)[1]
    assert "verify-checksums" in section
    assert "--fix" in section


def _code_blocks(text: str) -> str:
    """Everything inside ``` fences, which is the part readers copy.

    The hazard here is a *runnable* snippet, so this guard is narrower than
    `test_no_optional_parser.py`, which scans whole documents because the thing
    it hunts (a promise about installing a parser) lives in prose. Naming
    `pg_read_binary_file` in prose to explain why it is the wrong tool is the
    opposite of the defect.
    """
    parts = text.split("```")
    return "\n".join(parts[1::2])


def test_the_superuser_snippet_is_gone(text: str) -> None:
    """Not merely deprecated in place — a copyable snippet gets copied."""
    assert "pg_read_binary_file" not in _code_blocks(text)


def test_no_hand_written_update_of_the_checksum_column(text: str) -> None:
    """Any runnable `UPDATE … SET checksum` is the thing `--fix` exists to replace."""
    assert "set checksum" not in _code_blocks(text).lower()


def test_the_prose_still_warns_against_the_old_snippet(text: str) -> None:
    """Deleting it silently leaves anyone who copied it earlier none the wiser."""
    assert "pg_read_binary_file" in text, "say why the old snippet was wrong, not just drop it"
