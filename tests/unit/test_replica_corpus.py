"""Acceptance corpus: one case per replica-safety matrix row (issue #139, Phase 4).

End-to-end through the classifier + verdict, asserting safety, severity (under
replicas-declared), and multi-step remediation — the regression guard against
classifier/verdict drift the issue requires.

Since 0.43.0 each row also pins its **risk tier** (#197). The two verdicts answer
different questions and are deliberately independent: replica safety is
two-version forward-compatibility, the tier is what the change does to the data.
`RENAME COLUMN` is the row that shows it — replica-unsafe, yet `reversible`.
Pinning both here means a change that moves one without the other is visible.
"""

from __future__ import annotations

import pytest

from confiture.core.change_set import classify_statements
from confiture.core.replica.classifier import OperationClassifier
from confiture.core.replica.safety import classify_replica_safety, replica_severity
from confiture.core.risk_tier import RiskTier

# (sql, expected_safety, expected_severity_with_replicas, expected_risk_tier)
CORPUS = {
    "add_column_nullable": ("ALTER TABLE t ADD COLUMN c int;", "safe", None, RiskTier.ADDITIVE),
    "add_column_not_null_default": (
        "ALTER TABLE t ADD COLUMN c int NOT NULL DEFAULT 0;",
        "unsafe",
        "error",
        RiskTier.LOCK_RISKY,
    ),
    "drop_column": ("ALTER TABLE t DROP COLUMN c;", "unsafe", "error", RiskTier.IRREVERSIBLE),
    "rename_column": (
        "ALTER TABLE t RENAME COLUMN a TO b;",
        "unsafe",
        "error",
        RiskTier.REVERSIBLE,
    ),
    "change_type": ("ALTER TABLE t ALTER COLUMN c TYPE bigint;", "unsafe", "error", None),
    "add_constraint_immediate": (
        "ALTER TABLE t ADD CONSTRAINT ck CHECK (c > 0);",
        "unsafe",
        "error",
        RiskTier.LOCK_RISKY,
    ),
    "add_constraint_not_valid": (
        "ALTER TABLE t ADD CONSTRAINT ck CHECK (c > 0) NOT VALID;",
        "safe",
        None,
        RiskTier.REVERSIBLE,
    ),
    "create_index": ("CREATE INDEX idx ON t (c);", "unsafe", "error", RiskTier.LOCK_RISKY),
    "create_index_concurrently": (
        "CREATE INDEX CONCURRENTLY idx ON t (c);",
        "safe",
        None,
        RiskTier.ADDITIVE,
    ),
    "create_table": ("CREATE TABLE t (id int);", "safe", None, RiskTier.ADDITIVE),
}


@pytest.mark.parametrize("name", list(CORPUS))
def test_window_safe_still_derives_only_from_replica_findings(name: str, tmp_path) -> None:
    """#154's contract, re-proven end-to-end now that `change_set` rides beside it.

    `window_safe` is true iff no ``PFLIGHT_REPLICA_*`` finding is present. Adding
    the risk tier must not have moved it in either direction — including for
    `rename_column`, where the tier (`reversible`) and the verdict (unsafe)
    deliberately disagree.
    """
    import json

    from typer.testing import CliRunner

    from confiture.cli.main import app

    sql, safety, _sev, _tier = CORPUS[name]
    migrations = tmp_path / name
    migrations.mkdir()
    (migrations / "20260806120000_case.up.sql").write_text(sql)

    result = CliRunner().invoke(
        app,
        ["migrate", "preflight", "--migrations-dir", str(migrations), "--format", "json"],
    )
    payload = json.loads(result.stdout)

    replica_findings = [i for i in payload["issues"] if i["code"].startswith("PFLIGHT_REPLICA_")]
    assert payload["window_safe"] is (not replica_findings), name
    assert payload["window_safe"] is (safety == "safe"), name


@pytest.mark.parametrize("name", list(CORPUS))
def test_corpus_risk_tier(name: str) -> None:
    """The #197 tier for each matrix row."""
    sql, _safety, _sev, tier = CORPUS[name]
    (entry,) = classify_statements(sql)
    assert entry.tier is tier, name


@pytest.mark.parametrize("name", list(CORPUS))
def test_corpus_row(name: str) -> None:
    sql, safety, sev, _tier = CORPUS[name]
    [op] = OperationClassifier().classify(sql)
    verdict = classify_replica_safety(op)
    assert verdict.safety == safety, name
    if safety == "safe":
        return
    assert verdict.multi_step, name  # remediation present for unsafe
    assert replica_severity(verdict, has_replicas=True, bypass=False) == sev, name
    # Warn (not error) when no replicas are declared (soft default).
    assert replica_severity(verdict, has_replicas=False, bypass=False) == "warning", name
