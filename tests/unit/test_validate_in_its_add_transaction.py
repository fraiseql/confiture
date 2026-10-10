"""A ``VALIDATE CONSTRAINT`` in the transaction that adds the constraint scans under the ADD's lock.

A ``.up.sql`` runs as one script in confiture's transaction unless it holds a
statement PostgreSQL refuses there (``CREATE INDEX CONCURRENTLY`` …), and its
``BEGIN``/``COMMIT`` lines are stripped first. So ``ADD … NOT VALID; VALIDATE``
in one transactional file scans every row while the ADD's lock is held: SHARE
ROW EXCLUSIVE on both tables for a foreign key (writes wait), ACCESS EXCLUSIVE
for a check (reads wait too). Alone, the validation blocks nothing.
"""

import pytest

from confiture.core.change_set import classify_statements
from confiture.core.lock_profile import Duration, LockLevel, constraint_profile
from confiture.core.risk_tier import RiskTier

_FK = (
    "ALTER TABLE tb_user ADD CONSTRAINT fk_user_org FOREIGN KEY (org) "
    "REFERENCES tb_org (id) NOT VALID;\n"
)
_CHECK = "ALTER TABLE tb_user ADD CONSTRAINT ck_user_org CHECK (org > 0) NOT VALID;\n"


def _validation(sql: str):
    [entry] = [e for e in classify_statements(sql) if e.kind == "validate_constraint"]
    return entry


def test_alone_it_is_reversible_and_blocks_nothing() -> None:
    entry = _validation("ALTER TABLE tb_user VALIDATE CONSTRAINT fk_user_org;")

    assert entry.tier is RiskTier.REVERSIBLE
    assert not entry.lock.blocks_writes
    assert not entry.lock.blocks_reads


def test_after_its_foreign_key_add_writes_wait_on_the_scan() -> None:
    entry = _validation(_FK + "ALTER TABLE tb_user VALIDATE CONSTRAINT fk_user_org;")

    assert entry.tier is RiskTier.LOCK_RISKY
    assert entry.lock.lock is LockLevel.SHARE_ROW_EXCLUSIVE
    assert entry.lock.blocks_writes
    assert not entry.lock.blocks_reads
    assert entry.lock.duration is Duration.MINUTES_PLUS
    assert "tb_org" in (entry.detail or "")


def test_after_its_check_add_reads_wait_too() -> None:
    entry = _validation(_CHECK + "ALTER TABLE tb_user VALIDATE CONSTRAINT ck_user_org;")

    assert entry.tier is RiskTier.LOCK_RISKY
    assert entry.lock.lock is LockLevel.ACCESS_EXCLUSIVE
    assert entry.lock.blocks_reads


def test_a_migration_run_statement_by_statement_validates_alone() -> None:
    sql = (
        _FK
        + "CREATE INDEX CONCURRENTLY ix_user_org ON tb_user (org);\n"
        + "ALTER TABLE tb_user VALIDATE CONSTRAINT fk_user_org;"
    )

    assert _validation(sql).tier is RiskTier.REVERSIBLE


def test_a_commit_line_does_not_split_the_transaction() -> None:
    """confiture strips BEGIN/COMMIT lines and runs the file in its own transaction."""
    sql = _FK + "COMMIT;\nBEGIN;\nALTER TABLE tb_user VALIDATE CONSTRAINT fk_user_org;"

    assert _validation(sql).tier is RiskTier.LOCK_RISKY


@pytest.mark.parametrize(
    ("relation", "tier"),
    [("public.tb_user", RiskTier.LOCK_RISKY), ("other.tb_user", RiskTier.REVERSIBLE)],
)
def test_the_relation_is_matched_by_identity(relation: str, tier: RiskTier) -> None:
    sql = _FK + f"ALTER TABLE {relation} VALIDATE CONSTRAINT fk_user_org;"

    assert _validation(sql).tier is tier


def test_another_constraint_of_the_same_table_validates_alone() -> None:
    sql = _FK + "ALTER TABLE tb_user VALIDATE CONSTRAINT fk_other;"

    assert _validation(sql).tier is RiskTier.REVERSIBLE


def test_a_foreign_key_add_takes_share_row_exclusive() -> None:
    """PostgreSQL locks both tables SHARE ROW EXCLUSIVE for ADD FOREIGN KEY; a check, ACCESS EXCLUSIVE."""
    assert constraint_profile(not_valid=True, foreign_key=True).lock is (
        LockLevel.SHARE_ROW_EXCLUSIVE
    )
    assert constraint_profile(not_valid=True, foreign_key=False).lock is (
        LockLevel.ACCESS_EXCLUSIVE
    )
    [add] = classify_statements(_FK)
    assert add.lock.lock is LockLevel.SHARE_ROW_EXCLUSIVE
    assert add.tier is RiskTier.REVERSIBLE


def test_a_generated_foreign_key_is_tiered_as_the_pair_it_writes() -> None:
    """``tier_of`` on the seam agrees with the classifier over the generated pair."""
    from confiture.core.differ import SchemaDiffer
    from confiture.platform import tier_of

    old = "CREATE TABLE tb_org (id int PRIMARY KEY); CREATE TABLE tb_user (org int);"
    new = (
        "CREATE TABLE tb_org (id int PRIMARY KEY); CREATE TABLE tb_user (org int, "
        "CONSTRAINT fk_user_org FOREIGN KEY (org) REFERENCES tb_org (id));"
    )
    [change] = SchemaDiffer().compare(old, new).changes

    assert tier_of(change) is RiskTier.LOCK_RISKY
