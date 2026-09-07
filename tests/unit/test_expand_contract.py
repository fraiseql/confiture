"""The expand/contract plan: the classifier's advice as explicit, costed stages — a pure function.

Three patterns the replica classifier only *advises* today become staged
plans: add a NOT NULL column with a default (add it nullable → backfill →
prove NOT NULL through a validated CHECK), add a constraint (NOT VALID →
VALIDATE), and change a column's type (add a new column → dual-write →
backfill → swap → drop the old one). Every stage carries the lock the
lock-profile table gives its statements, and the longest ACCESS EXCLUSIVE hold
a stage takes — the number the online e2e measures.
"""

from __future__ import annotations

from confiture.core.expand_contract import plan

ADD_NOT_NULL = "ALTER TABLE orders ADD COLUMN status text NOT NULL DEFAULT 'new';"
ADD_CHECK = "ALTER TABLE orders ADD CONSTRAINT orders_total_positive CHECK (total >= 0);"
CHANGE_TYPE = "ALTER TABLE orders ALTER COLUMN total TYPE bigint;"


def _stages(sql: str) -> list[dict]:
    plans = plan(sql, server_version=15)
    assert len(plans) == 1, plans
    return plans[0].to_dict()["stages"]


def test_a_safe_migration_has_no_plan() -> None:
    assert plan("CREATE TABLE t (id integer PRIMARY KEY);", server_version=15) == []


def test_add_not_null_column_expands_backfills_then_proves_not_null() -> None:
    plans = plan(ADD_NOT_NULL, server_version=15)
    assert [p.pattern for p in plans] == ["add_not_null_column"]
    assert plans[0].to_dict() == {
        "pattern": "add_not_null_column",
        "table": "orders",
        "stages": [
            {
                "stage": "expand",
                "statements": [
                    "ALTER TABLE orders ADD COLUMN status text DEFAULT 'new'",
                    "ALTER TABLE orders ADD CONSTRAINT orders_status_not_null "
                    "CHECK (status IS NOT NULL) NOT VALID",
                ],
                "lock": "access_exclusive",
                "duration": "metadata",
                "exclusive_hold": "metadata",
                "backfill": None,
                "destructive": False,
            },
            {
                "stage": "backfill",
                "statements": [],
                "lock": "none",
                "duration": "minutes+",
                "exclusive_hold": None,
                "backfill": {
                    "table": "orders",
                    "column": "status",
                    "expression": "'new'",
                    "where_clause": "status IS NULL",
                },
                "destructive": False,
            },
            {
                "stage": "contract",
                "statements": [
                    "ALTER TABLE orders VALIDATE CONSTRAINT orders_status_not_null",
                    "ALTER TABLE orders ALTER COLUMN status SET NOT NULL",
                    "ALTER TABLE orders DROP CONSTRAINT orders_status_not_null",
                ],
                "lock": "access_exclusive",
                "duration": "minutes+",
                "exclusive_hold": "metadata",
                "backfill": None,
                "destructive": False,
            },
        ],
    }


def test_add_constraint_is_not_valid_then_validated() -> None:
    stages = _stages(ADD_CHECK)
    assert [s["stage"] for s in stages] == ["expand", "contract"]
    assert stages[0]["statements"] == [
        "ALTER TABLE orders ADD CONSTRAINT orders_total_positive CHECK (total >= 0) NOT VALID"
    ]
    assert stages[0]["exclusive_hold"] == "metadata"
    assert stages[1]["statements"] == [
        "ALTER TABLE orders VALIDATE CONSTRAINT orders_total_positive"
    ]
    assert stages[1]["lock"] == "share_update_exclusive"
    assert stages[1]["exclusive_hold"] is None


def test_change_type_adds_dual_writes_backfills_swaps_then_drops() -> None:
    stages = _stages(CHANGE_TYPE)
    assert [s["stage"] for s in stages] == ["expand", "backfill", "contract"]
    assert stages[0]["statements"] == [
        "ALTER TABLE orders ADD COLUMN total__new bigint",
        "CREATE FUNCTION orders_total_dual_write() RETURNS trigger LANGUAGE plpgsql AS "
        "$$ BEGIN NEW.total__new := NEW.total::bigint; RETURN NEW; END $$",
        "CREATE TRIGGER orders_total_dual_write BEFORE INSERT OR UPDATE ON orders "
        "FOR EACH ROW EXECUTE FUNCTION orders_total_dual_write()",
    ]
    assert stages[0]["exclusive_hold"] == "metadata"
    assert stages[1]["backfill"] == {
        "table": "orders",
        "column": "total__new",
        "expression": "total::bigint",
        "where_clause": "total__new IS NULL",
    }
    assert stages[2]["statements"] == [
        "DROP TRIGGER orders_total_dual_write ON orders",
        "DROP FUNCTION orders_total_dual_write()",
        "ALTER TABLE orders RENAME COLUMN total TO total__old",
        "ALTER TABLE orders RENAME COLUMN total__new TO total",
        "ALTER TABLE orders DROP COLUMN total__old",
    ]
    assert stages[2]["destructive"] is True
    assert stages[2]["exclusive_hold"] == "metadata"


def test_the_plan_is_pure_and_stable() -> None:
    assert plan(ADD_NOT_NULL, server_version=15) == plan(ADD_NOT_NULL, server_version=15)
    assert (
        plan(ADD_NOT_NULL + ADD_CHECK, server_version=15)[1].pattern == "add_constraint_not_valid"
    )
