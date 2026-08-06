"""Lock cost and DB-refined type direction on the change set (issue #199, cycles 5-6).

Two things reach the change set that could not before:

* Every entry carries what the operation costs in locking terms, so a catalog
  write is distinguishable from a full-table rewrite without re-deriving it from
  ``kind``. It rides as a typed field and in ``detail``, **not** on the wire —
  the entry shape is the ratified fraisier-core#44 pact.
* When a database is reachable, the *current* column type is known, so
  ``ALTER COLUMN … TYPE`` finally gets a direction and therefore a tier.

The static path must be unchanged by all of this: preflight is a filesystem-only
check by design, and the DB layer is strictly additive.
"""

from __future__ import annotations

import pytest

from confiture.core.change_set import build_change_set, classify_statements
from confiture.core.lock_profile import Duration
from confiture.core.risk_tier import RiskTier
from confiture.core.schema_facts import SchemaFacts

# --------------------------------------------------------------------------- #
# Cycle 5: the lock profile rides on the entry
# --------------------------------------------------------------------------- #


def test_entry_carries_lock_profile() -> None:
    (entry,) = classify_statements("ALTER TABLE t ADD COLUMN c int;")
    assert entry.lock is not None
    assert entry.lock.rewrites_table is False
    assert entry.lock.duration is Duration.METADATA


def test_rewrite_is_distinguishable_from_metadata() -> None:
    """#199's headline criterion, as two entries that must not look alike."""
    (cheap,) = classify_statements("ALTER TABLE t DROP COLUMN c;")
    (expensive,) = classify_statements("ALTER TABLE t ALTER COLUMN c TYPE bigint;")

    assert cheap.lock.rewrites_table is False
    assert cheap.lock.duration is Duration.METADATA
    assert expensive.lock.rewrites_table is True
    assert expensive.lock.duration is Duration.MINUTES_PLUS


def test_lock_stays_off_the_wire() -> None:
    """The entry shape is the ratified fraisier-core#44 pact, pinned byte-for-byte.

    Adding a key is a co-ordinated cross-repo change with a `contract_version`
    decision, so the lock facts travel through `detail` (free-form by
    specification) and the typed field, not the wire.
    """
    (entry,) = classify_statements("CREATE INDEX idx ON t (c);")
    assert entry.lock is not None
    assert "lock" not in entry.to_dict()
    assert set(entry.to_dict()) <= {"kind", "object", "migration", "tier", "detail"}


def test_python_migration_has_no_lock(tmp_path) -> None:
    """No statement to cost ⇒ no profile, rather than a fabricated cheap one."""
    migrations = tmp_path / "m"
    migrations.mkdir()
    (migrations / "20260806120000_a.py").write_text("def up(conn):\n    pass\n")
    change_set = build_change_set(migrations)
    (entry,) = change_set.changes
    assert entry.kind == "python_migration"
    assert entry.lock is None


# --------------------------------------------------------------------------- #
# Cycle 6: DB-refined answers
# --------------------------------------------------------------------------- #


def test_alter_column_type_is_unclassified_without_facts() -> None:
    """Today's behaviour, unchanged: no old type ⇒ no tier."""
    (entry,) = classify_statements("ALTER TABLE public.t ALTER COLUMN c TYPE integer;")
    assert entry.tier is None


def test_narrowing_is_irreversible_with_facts() -> None:
    facts = SchemaFacts(column_types={"public.t.c": "bigint"})
    (entry,) = classify_statements("ALTER TABLE public.t ALTER COLUMN c TYPE integer;", facts=facts)
    assert entry.tier is RiskTier.IRREVERSIBLE
    assert "narrow" in (entry.detail or "").lower()


def test_widening_that_rewrites_is_lock_risky() -> None:
    facts = SchemaFacts(column_types={"public.t.c": "integer"})
    (entry,) = classify_statements("ALTER TABLE public.t ALTER COLUMN c TYPE bigint;", facts=facts)
    assert entry.tier is RiskTier.LOCK_RISKY


def test_widening_without_a_rewrite_is_reversible() -> None:
    """`varchar(50)`→`text` is binary coercible: no rewrite, no lock risk."""
    facts = SchemaFacts(column_types={"public.t.c": "varchar(50)"})
    (entry,) = classify_statements("ALTER TABLE public.t ALTER COLUMN c TYPE text;", facts=facts)
    assert entry.tier is RiskTier.REVERSIBLE
    assert entry.lock.rewrites_table is False


def test_unmodelled_type_stays_unclassified_even_with_facts() -> None:
    facts = SchemaFacts(column_types={"public.t.c": "mood"})
    (entry,) = classify_statements("ALTER TABLE public.t ALTER COLUMN c TYPE text;", facts=facts)
    assert entry.tier is None


@pytest.mark.parametrize(
    ("server_version", "expected"),
    [
        (None, RiskTier.LOCK_RISKY),
        (10, RiskTier.LOCK_RISKY),
        (11, RiskTier.ADDITIVE),
        (16, RiskTier.ADDITIVE),
    ],
)
def test_add_column_default_refines_with_server_version(
    server_version: int | None, expected: RiskTier
) -> None:
    """PG 11's fast default turns the rewrite into a catalog write.

    Unknown version keeps the conservative reading, so the no-connection default
    is byte-identical to before.
    """
    facts = SchemaFacts(server_version=server_version) if server_version else None
    (entry,) = classify_statements(
        "ALTER TABLE t ADD COLUMN c int NOT NULL DEFAULT 0;", facts=facts
    )
    assert entry.tier is expected


def test_facts_do_not_change_unrelated_entries() -> None:
    """The DB layer is additive: an entry it says nothing about is untouched."""
    sql = "DROP TABLE t; CREATE TABLE u (id int);"
    without = classify_statements(sql)
    with_facts = classify_statements(sql, facts=SchemaFacts(server_version=16))
    assert [e.kind for e in without] == [e.kind for e in with_facts]
    assert [e.tier for e in without] == [e.tier for e in with_facts]


def test_build_change_set_threads_facts(tmp_path) -> None:
    migrations = tmp_path / "m"
    migrations.mkdir()
    (migrations / "20260806120000_a.up.sql").write_text(
        "ALTER TABLE public.t ALTER COLUMN c TYPE integer;"
    )

    facts = SchemaFacts(column_types={"public.t.c": "bigint"})
    change_set = build_change_set(migrations, facts=facts)
    assert change_set.worst_tier is RiskTier.IRREVERSIBLE


def test_schema_facts_lookup_is_case_folded() -> None:
    facts = SchemaFacts(column_types={"public.t.c": "bigint"})
    assert facts.column_type("PUBLIC.T.C") == "bigint"
    assert facts.column_type("public.other.c") is None
