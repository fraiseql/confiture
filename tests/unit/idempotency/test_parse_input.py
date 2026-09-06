"""pglast receives the raw file (Phase 05, ANA-01).

The validator used to blank ``--`` to end of line and mask ``$tag$…$tag$`` with
a tag-blind regex before parsing. ``'a--b'`` lost its closing quote, a ``$q$``
inside a ``$body$`` was cut in two, pglast failed on the corrupted text and the
dispatcher swapped to the regex backend without a word — reporting a
``CREATE TABLE`` that lives inside a function body, or missing one that
followed a literal on the same line. Positions now come from pglast's own
statement locations on the untouched text.
"""

from __future__ import annotations

from confiture.core.idempotency.models import IdempotencyPattern
from confiture.core.idempotency.validator import IdempotencyValidator

NESTED_TAGS = """\
CREATE OR REPLACE FUNCTION f() RETURNS void AS $body$
BEGIN
  EXECUTE $q$CREATE TABLE inner_t (id int)$q$;
END
$body$ LANGUAGE plpgsql;
"""

LITERAL_WITH_DASHES = "INSERT INTO t VALUES ('a--b'); CREATE TABLE t2 (id int);\n"

COMMENTED_OUT = """\
-- CREATE TABLE commented (id int);
/* CREATE TABLE
   also_commented (id int); */
CREATE TABLE real_one (id int);
"""


def _patterns(sql: str) -> list[tuple[IdempotencyPattern, int]]:
    report = IdempotencyValidator().validate_sql(sql, file_path="probe.sql")
    return [(v.pattern, v.line_number) for v in report.violations]


def test_ddl_inside_a_nested_dollar_body_is_not_a_finding() -> None:
    """Only the function statement itself is reported (its usual shape-risk note)."""
    assert _patterns(NESTED_TAGS) == [
        (IdempotencyPattern.CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK, 1),
    ]


def test_a_literal_containing_dashes_does_not_swallow_the_rest_of_the_line() -> None:
    assert _patterns(LITERAL_WITH_DASHES) == [(IdempotencyPattern.CREATE_TABLE, 1)]


def test_commented_out_ddl_is_not_a_finding_and_lines_are_the_originals() -> None:
    assert _patterns(COMMENTED_OUT) == [(IdempotencyPattern.CREATE_TABLE, 4)]


def test_the_validator_has_no_preprocessing_step() -> None:
    assert not hasattr(IdempotencyValidator, "_preprocess_sql")
