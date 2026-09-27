"""A key's target is the table its ``REFERENCES`` names, not one guessed from its name (#498).

Level 3 read ``fk_owner`` as a key to ``tb_owner``. A key named for its role (an
owner, a parent, a company that is an organization) drew a false
``MISSING_FK_TRANSFORMATION`` against a resolver that joins exactly the table the
schema declares. The target is the final table's foreign key; only an ``fk_*``
column with no ``REFERENCES`` falls back to the name. A key resolved in a
second-pass ``UPDATE`` is resolved, and a routine named ``fn_resolve_…`` that
takes arguments is not a resolver: levels 4 and 5 call one with none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture import platform
from confiture.core.seed.validation.prep_seed.models import PrepSeedPattern

TABLES = """
CREATE SCHEMA catalog; CREATE SCHEMA prep_seed; CREATE SCHEMA core;
CREATE TABLE catalog.tb_person (pk_person BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID NOT NULL UNIQUE, name TEXT NOT NULL);
CREATE TABLE catalog.tb_widget (pk_widget BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID NOT NULL UNIQUE,
    fk_owner BIGINT REFERENCES catalog.tb_person (pk_person),
    fk_parent_widget BIGINT REFERENCES catalog.tb_widget (pk_widget));
CREATE TABLE prep_seed.tb_person (id UUID NOT NULL, name TEXT NOT NULL);
CREATE TABLE prep_seed.tb_widget (id UUID NOT NULL, fk_owner_id UUID, fk_parent_widget_id UUID);
CREATE FUNCTION catalog.fn_resolve_tb_person() RETURNS void LANGUAGE plpgsql AS $$
BEGIN INSERT INTO catalog.tb_person (id, name) SELECT id, name FROM prep_seed.tb_person; END $$;
"""

#: Joins the owner, then resolves the self-reference in a second pass.
JOIN_THEN_UPDATE = """
CREATE FUNCTION catalog.fn_resolve_tb_widget() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO catalog.tb_widget (id, fk_owner)
  SELECT w.id, p.pk_person FROM prep_seed.tb_widget w
  LEFT JOIN catalog.tb_person p ON p.id = w.fk_owner_id;
  UPDATE catalog.tb_widget t SET fk_parent_widget = parent.pk_widget
  FROM prep_seed.tb_widget s JOIN catalog.tb_widget parent ON parent.id = s.fk_parent_widget_id
  WHERE t.id = s.id AND s.fk_parent_widget_id IS NOT NULL;
END $$;
"""

#: The owner resolved with a scalar subquery rather than a join.
SUBQUERY_THEN_UPDATE = """
CREATE FUNCTION catalog.fn_resolve_tb_widget() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO catalog.tb_widget (id, fk_owner)
  SELECT s.id, (SELECT pk_person FROM catalog.tb_person WHERE id = s.fk_owner_id)
  FROM prep_seed.tb_widget s;
  UPDATE catalog.tb_widget t SET fk_parent_widget = parent.pk_widget
  FROM prep_seed.tb_widget s JOIN catalog.tb_widget parent ON parent.id = s.fk_parent_widget_id
  WHERE t.id = s.id;
END $$;
"""

#: Never resolves the owner.
NO_OWNER = """
CREATE FUNCTION catalog.fn_resolve_tb_widget() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO catalog.tb_widget (id) SELECT w.id FROM prep_seed.tb_widget w;
  UPDATE catalog.tb_widget t SET fk_parent_widget = parent.pk_widget
  FROM prep_seed.tb_widget s JOIN catalog.tb_widget parent ON parent.id = s.fk_parent_widget_id
  WHERE t.id = s.id;
END $$;
"""

#: A business routine that happens to be named like a resolver; it takes an argument.
BUSINESS = """
CREATE FUNCTION core.fn_resolve_or_create_widget(p_owner_pk BIGINT) RETURNS void LANGUAGE plpgsql AS $$
BEGIN INSERT INTO catalog.tb_widget (id, fk_owner) VALUES (gen_random_uuid(), p_owner_pk); END $$;
"""


def _report(tmp_path: Path, ddl: str) -> platform.PrepSeedReport:
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "10_tables.sql").write_text(ddl)
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    return platform.validate_seeds(seeds, schema_dir=schema, max_level=3)


def _messages(report: platform.PrepSeedReport, pattern: PrepSeedPattern) -> list[str]:
    return [v.message for v in report.violations if v.pattern == pattern]


@pytest.mark.parametrize("resolver", [JOIN_THEN_UPDATE, SUBQUERY_THEN_UPDATE])
def test_a_key_named_for_its_role_resolved_to_its_referenced_table_is_resolved(
    tmp_path: Path, resolver: str
) -> None:
    report = _report(tmp_path, TABLES + resolver)

    assert _messages(report, PrepSeedPattern.MISSING_FK_TRANSFORMATION) == []


def test_an_unresolved_key_names_the_table_it_references(tmp_path: Path) -> None:
    (message,) = _messages(
        _report(tmp_path, TABLES + NO_OWNER), PrepSeedPattern.MISSING_FK_TRANSFORMATION
    )

    assert "tb_person on fk_owner_id" in message


def test_a_self_reference_resolved_in_a_second_pass_draws_no_warning(tmp_path: Path) -> None:
    report = _report(tmp_path, TABLES + JOIN_THEN_UPDATE)

    assert _messages(report, PrepSeedPattern.MISSING_SELF_REFERENCE_HANDLING) == []


def test_a_self_reference_with_no_second_pass_is_still_warned(tmp_path: Path) -> None:
    resolver = JOIN_THEN_UPDATE[: JOIN_THEN_UPDATE.index("  UPDATE")] + "END $$;\n"

    (message,) = _messages(
        _report(tmp_path, TABLES + resolver), PrepSeedPattern.MISSING_SELF_REFERENCE_HANDLING
    )
    assert "fk_parent_widget_id" in message


def test_a_self_reference_is_read_from_references_not_the_name(tmp_path: Path) -> None:
    """``fk_owner`` references ``tb_person``: no two-pass warning, whatever its name says."""
    ddl = TABLES.replace("fk_owner BIGINT", "fk_widget_owner BIGINT").replace(
        "fk_owner_id UUID", "fk_widget_owner_id UUID"
    )
    resolver = JOIN_THEN_UPDATE.replace("fk_owner", "fk_widget_owner")

    messages = _messages(
        _report(tmp_path, ddl + resolver), PrepSeedPattern.MISSING_SELF_REFERENCE_HANDLING
    )

    assert messages == []


def test_a_routine_that_takes_arguments_is_not_a_resolver(tmp_path: Path) -> None:
    report = _report(tmp_path, TABLES + JOIN_THEN_UPDATE + BUSINESS)

    assert not any("fn_resolve_or_create_widget" in v.message for v in report.violations)


def test_a_key_with_no_references_falls_back_to_its_name(tmp_path: Path) -> None:
    """``fk_color_id`` with no ``REFERENCES`` anywhere is a key to ``tb_color`` by convention."""
    ddl = TABLES.replace(
        "CREATE TABLE prep_seed.tb_widget (id UUID NOT NULL,",
        "CREATE TABLE catalog.tb_color (pk_color BIGINT PRIMARY KEY, id UUID NOT NULL UNIQUE);\n"
        "CREATE TABLE prep_seed.tb_widget (id UUID NOT NULL, fk_color_id UUID,",
    ).replace("fk_owner BIGINT REFERENCES", "fk_color BIGINT, fk_owner BIGINT REFERENCES")

    (message,) = _messages(
        _report(tmp_path, ddl + JOIN_THEN_UPDATE), PrepSeedPattern.MISSING_FK_TRANSFORMATION
    )
    assert "tb_color on fk_color_id" in message
