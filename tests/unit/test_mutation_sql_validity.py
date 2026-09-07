"""Every default mutation produces SQL PostgreSQL would accept.

A mutation weakens a migration so that a weak test suite lets it *survive*; a
mutation that turns the migration into a syntax error is "killed" by the parser
before any test runs and tells you nothing about the tests. ``schema_001``
did exactly that — its regex swallowed the comma after ``PRIMARY KEY``.
"""

from __future__ import annotations

import pytest

from confiture.testing.frameworks.mutation import MutationCategory, MutationRegistry

pglast = pytest.importorskip("pglast")

_SAMPLES = {
    MutationCategory.SCHEMA: [
        "CREATE TABLE widgets (id INT PRIMARY KEY, label TEXT NOT NULL, code TEXT UNIQUE);",
        (
            "CREATE TABLE orders (\n"
            "    id INT NOT NULL,\n"
            "    widget_id INT NOT NULL,\n"
            "    qty INT DEFAULT 1 CHECK (qty > 0),\n"
            "    PRIMARY KEY (id),\n"
            "    FOREIGN KEY (widget_id) REFERENCES widgets (id)\n"
            ");"
        ),
        "CREATE UNIQUE INDEX idx_widgets_code ON widgets (code);",
        "ALTER TABLE widgets ADD COLUMN note TEXT DEFAULT 'none';",
    ],
    MutationCategory.DATA: [
        "UPDATE widgets SET label = COALESCE(label, 'x') WHERE id = 1;",
        "INSERT INTO widgets (id, label) VALUES (3, 'c');",
        "DELETE FROM widgets WHERE id = 2;",
        "SELECT id::TEXT FROM widgets;",
        "UPDATE widgets SET status = 'active' WHERE id > 0;",
        "UPDATE widgets SET label = 'y';",
    ],
    MutationCategory.ROLLBACK: [
        "DROP TABLE widgets;",
        "INSERT INTO widgets SELECT * FROM widgets_backup;",
        "ALTER TABLE widgets DROP COLUMN note;",
        "DROP INDEX idx_widgets_code;",
    ],
    MutationCategory.PERFORMANCE: [
        "CREATE INDEX CONCURRENTLY idx_widgets_label ON widgets (label);",
        "UPDATE widgets SET label = 'x';",
        "UPDATE widgets SET label = 'x' WHERE id = 1;",
    ],
}


def _applicable_cases():
    """(mutation, sample) pairs where the mutation changes the sample.

    Built at collection time, so an inapplicable pair is not a test (and not a
    skip); ``test_every_mutation_applies_to_a_sample`` fails when a mutation has
    no applicable sample at all, which is the case that would otherwise hide.
    """
    registry = MutationRegistry()
    for mutation in registry.list_all():
        for sample in _SAMPLES.get(mutation.category, []):
            if mutation.apply(sample) != sample:
                yield pytest.param(mutation, sample, id=f"{mutation.id}-{sample[:28]!r}")


def test_every_mutation_applies_to_a_sample() -> None:
    registry = MutationRegistry()
    orphans = [
        f"{m.id} ({m.name})"
        for m in registry.list_all()
        if not any(m.apply(s) != s for s in _SAMPLES.get(m.category, []))
    ]
    assert orphans == [], f"mutations no sample exercises: {orphans}"


@pytest.mark.parametrize(("mutation", "sample"), list(_applicable_cases()))
def test_applied_mutation_is_valid_sql(mutation, sample: str) -> None:
    mutated = mutation.apply(sample)
    assert mutated != sample
    try:
        pglast.parse_sql(mutated)
    except pglast.parser.ParseError as exc:
        pytest.fail(f"{mutation.id} ({mutation.name}) produced invalid SQL:\n{mutated}\n{exc}")
