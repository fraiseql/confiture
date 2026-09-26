"""A partition takes its parent's scope, and its key, in every tenant rule (#466).

A partition holds its parent's rows: a view, an ``INSERT`` or a foreign key written
against ``app.tb_event_2026`` reads, writes or points at tenant rows exactly as one
written against ``app.tb_event`` does. It is still never judged on its own for what
its parent declares — ``tenant_002`` and ``tenant_005`` report the parent once.
"""

from __future__ import annotations

from pathlib import Path

from tests.unit.linting.tenant_projects import SCOPED, findings

_EVENT = (
    f"CREATE TABLE app.tb_event (id uuid NOT NULL, at date NOT NULL, {SCOPED},\n"
    "  PRIMARY KEY (tenant_id, id, at)) PARTITION BY RANGE (at);\n"
    "CREATE TABLE app.tb_event_2026 PARTITION OF app.tb_event\n"
    "  FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');\n"
)

#: A partition of a partition: the scope is the root of the partition tree's.
_SUB = (
    "CREATE TABLE app.tb_event_2027 PARTITION OF app.tb_event\n"
    "  FOR VALUES FROM ('2027-01-01') TO ('2028-01-01') PARTITION BY RANGE (at);\n"
    "CREATE TABLE app.tb_event_2027_h1 PARTITION OF app.tb_event_2027\n"
    "  FOR VALUES FROM ('2027-01-01') TO ('2027-07-01');\n"
)


def _function(body: str) -> str:
    return (
        "CREATE FUNCTION app.fn_log(p_tenant uuid) RETURNS void LANGUAGE plpgsql AS $$\n"
        f"BEGIN\n{body}\nEND;\n$$;\n"
    )


# -- tenant_003 ------------------------------------------------------------------


def test_a_view_hiding_the_discriminator_of_a_partition_is_reported(tmp_path: Path) -> None:
    found, _ = findings(
        tmp_path,
        _EVENT + "CREATE VIEW app.v_event AS SELECT id, at FROM app.tb_event_2026;\n",
        "tenant_003",
        "check_tenant_views",
    )

    (finding,) = found
    assert finding.object_name == "app.v_event"
    assert "app.tb_event_2026" in finding.message


def test_a_view_publishing_a_partitions_discriminator_is_traced(tmp_path: Path) -> None:
    found, _ = findings(
        tmp_path,
        _EVENT + "CREATE VIEW app.v_event AS SELECT tenant_id, id FROM app.tb_event_2026;\n",
        "tenant_003",
        "check_tenant_views",
    )

    assert found == []


def test_a_view_over_a_partition_of_a_partition_is_reported(tmp_path: Path) -> None:
    found, _ = findings(
        tmp_path,
        _EVENT + _SUB + "CREATE VIEW app.v_event AS SELECT id FROM app.tb_event_2027_h1;\n",
        "tenant_003",
        "check_tenant_views",
    )

    assert [f.object_name for f in found] == ["app.v_event"]


# -- tenant_001 ------------------------------------------------------------------


def test_an_insert_into_a_partition_without_the_discriminator_is_reported(
    tmp_path: Path,
) -> None:
    found, _ = findings(
        tmp_path,
        _EVENT
        + _function("  INSERT INTO app.tb_event_2026 (id, at) VALUES (gen_random_uuid(), now());"),
        "tenant_001",
        "check_tenant_isolation",
    )

    (finding,) = found
    assert finding.object_name == "app.fn_log -> app.tb_event_2026"
    assert "inserts into app.tb_event_2026 without tenant_id" in finding.message


def test_an_insert_into_a_partition_by_position_counts_the_parents_columns(
    tmp_path: Path,
) -> None:
    found, _ = findings(
        tmp_path,
        _EVENT
        + _function("  INSERT INTO app.tb_event_2026 VALUES (gen_random_uuid(), now(), p_tenant);"),
        "tenant_001",
        "check_tenant_isolation",
    )

    assert found == []


# -- tenant_004 ------------------------------------------------------------------


def test_a_foreign_key_to_a_partition_that_crosses_tenants_is_reported(tmp_path: Path) -> None:
    found, _ = findings(
        tmp_path,
        _EVENT
        + f"CREATE TABLE app.tb_note (id uuid PRIMARY KEY, {SCOPED}, fk_event uuid, at date,\n"
        "  FOREIGN KEY (fk_event, at) REFERENCES app.tb_event_2026 (id, at));\n",
        "tenant_004",
        "check_tenant_foreign_keys",
    )

    (finding,) = found
    assert finding.object_name == "app.tb_note"
    assert "→ app.tb_event_2026 (id, at)" in finding.message
    assert "REFERENCES app.tb_event_2026 (tenant_id, id, at)" in (finding.suggested_fix or "")
    assert "needs PRIMARY KEY" not in (finding.suggested_fix or "")


def test_a_foreign_key_to_a_partition_carrying_the_discriminator_is_clean(
    tmp_path: Path,
) -> None:
    found, _ = findings(
        tmp_path,
        _EVENT
        + f"CREATE TABLE app.tb_note (id uuid PRIMARY KEY, {SCOPED}, fk_event uuid, at date,\n"
        "  FOREIGN KEY (tenant_id, fk_event, at)\n"
        "    REFERENCES app.tb_event_2026 (tenant_id, id, at));\n",
        "tenant_004",
        "check_tenant_foreign_keys",
    )

    assert found == []


def test_a_global_table_pointing_at_a_partition_is_reported(tmp_path: Path) -> None:
    found, _ = findings(
        tmp_path,
        _EVENT + "CREATE TABLE catalog.tb_pin (id uuid PRIMARY KEY, fk_event uuid, at date,\n"
        "  FOREIGN KEY (fk_event, at) REFERENCES app.tb_event_2026 (id, at));\n",
        "tenant_004",
        "check_tenant_foreign_keys",
    )

    (finding,) = found
    assert finding.object_name == "catalog.tb_pin"
    assert "app.tb_event_2026" in finding.message


# -- never on its own ----------------------------------------------------------------


def test_a_partition_is_not_reported_for_what_its_parent_declares(tmp_path: Path) -> None:
    sql = (
        "CREATE TABLE app.tb_log (id uuid NOT NULL, at date NOT NULL) PARTITION BY RANGE (at);\n"
        "CREATE TABLE app.tb_log_2026 PARTITION OF app.tb_log\n"
        "  FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');\n"
    )
    found, _ = findings(tmp_path, sql, "tenant_002", "check_tenant_tables")

    assert [f.object_name for f in found] == ["app.tb_log"]
