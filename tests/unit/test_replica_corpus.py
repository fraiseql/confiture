"""Acceptance corpus: one case per replica-safety matrix row (issue #139, Phase 4).

End-to-end through the classifier + verdict, asserting safety, severity (under
replicas-declared), and multi-step remediation — the regression guard against
classifier/verdict drift the issue requires.
"""

from __future__ import annotations

import pytest

from confiture.core.replica.classifier import OperationClassifier
from confiture.core.replica.safety import classify_replica_safety, replica_severity

# (sql, expected_safety, expected_severity_with_replicas)
CORPUS = {
    "add_column_nullable": ("ALTER TABLE t ADD COLUMN c int;", "safe", None),
    "add_column_not_null_default": (
        "ALTER TABLE t ADD COLUMN c int NOT NULL DEFAULT 0;",
        "unsafe",
        "error",
    ),
    "drop_column": ("ALTER TABLE t DROP COLUMN c;", "unsafe", "error"),
    "rename_column": ("ALTER TABLE t RENAME COLUMN a TO b;", "unsafe", "error"),
    "change_type": ("ALTER TABLE t ALTER COLUMN c TYPE bigint;", "unsafe", "error"),
    "add_constraint_immediate": (
        "ALTER TABLE t ADD CONSTRAINT ck CHECK (c > 0);",
        "unsafe",
        "error",
    ),
    "add_constraint_not_valid": (
        "ALTER TABLE t ADD CONSTRAINT ck CHECK (c > 0) NOT VALID;",
        "safe",
        None,
    ),
    "create_index": ("CREATE INDEX idx ON t (c);", "unsafe", "error"),
    "create_index_concurrently": ("CREATE INDEX CONCURRENTLY idx ON t (c);", "safe", None),
    "create_table": ("CREATE TABLE t (id int);", "safe", None),
}


@pytest.mark.parametrize("name", list(CORPUS))
def test_corpus_row(name: str) -> None:
    sql, safety, sev = CORPUS[name]
    [op] = OperationClassifier().classify(sql)
    verdict = classify_replica_safety(op)
    assert verdict.safety == safety, name
    if safety == "safe":
        return
    assert verdict.multi_step, name  # remediation present for unsafe
    assert replica_severity(verdict, has_replicas=True, bypass=False) == sev, name
    # Warn (not error) when no replicas are declared (soft default).
    assert replica_severity(verdict, has_replicas=False, bypass=False) == "warning", name
