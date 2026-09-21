"""A ``plpgsql_check`` finding says what it is: a body that raises, or an artefact (#354).

Measured on a downstream tree, 132 of 177 findings were artefacts of how the
analysis is done — a TEMP table only a running body creates, a RECORD the analyser
cannot follow, a ``dblink`` call into an extension the scratch database lacks — and
a baseline keyed per routine let an artefact entry absorb every later *real* error
on the same routine. So each artefact class is a ``body`` code of its own:
``body_001`` keeps "the body raises", and selection is the registry's.

The diagnoses here are texts ``plpgsql_check`` returns; the ``plpgsql-check`` CI leg
asks the extension itself.
"""

from __future__ import annotations

from confiture.core.linting import bodies, references
from confiture.core.linting.baseline import Baseline
from confiture.core.linting.gate import Threshold
from confiture.core.linting.rule_registry import LINT_RULES
from confiture.core.linting.selection import linter_config


def _diagnosis(sqlstate: str, message: str, name: str = "fn") -> bodies.Diagnosis:
    return bodies.Diagnosis(
        schema="app",
        name=name,
        arity=0,
        kind="function",
        identity=f"app.{name}()",
        body_line=3,
        level="error",
        sqlstate=sqlstate,
        message=message,
        hint=None,
    )


TEMP = frozenset({"tmp_orders"})


def test_a_missing_relation_a_body_creates_temp_is_a_temp_table_artefact() -> None:
    missing = _diagnosis("42P01", 'relation "tmp_orders" does not exist')

    assert bodies.classify(missing, TEMP) == "temp_table"


def test_a_qualified_or_unknown_missing_relation_is_real() -> None:
    assert (
        bodies.classify(_diagnosis("42P01", 'relation "app.tmp_orders" does not exist'), TEMP)
        == "real"
    )
    assert bodies.classify(_diagnosis("42P01", 'relation "orders" does not exist'), TEMP) == "real"


def test_an_unassigned_record_is_a_record_artefact() -> None:
    unassigned = _diagnosis("55000", 'record "r" is not assigned yet')

    assert bodies.classify(unassigned, TEMP) == "record"


def test_a_dblink_call_into_a_missing_extension_is_a_dblink_artefact() -> None:
    missing = _diagnosis("42883", "function dblink_exec(unknown, unknown) does not exist")

    assert bodies.classify(missing, TEMP) == "dblink"


def test_anything_else_that_raises_is_real() -> None:
    assert bodies.classify(_diagnosis("42703", 'column "x" does not exist'), TEMP) == "real"


def test_each_class_is_a_code_of_its_own_and_carries_its_class() -> None:
    diagnoses = [
        _diagnosis("42703", 'column "x" does not exist'),
        _diagnosis("42P01", 'relation "tmp_orders" does not exist'),
        _diagnosis("55000", 'record "r" is not assigned yet'),
        _diagnosis("42883", "function dblink(unknown, unknown) does not exist"),
    ]

    found = bodies.findings(diagnoses, {}, temp=TEMP)

    assert [(v.rule_id, v.finding_class) for v in found] == [
        ("body_001", "real"),
        ("body_003", "temp_table"),
        ("body_004", "record"),
        ("body_005", "dblink"),
    ]


def test_an_artefact_in_the_baseline_does_not_absorb_a_real_error_on_the_same_routine() -> None:
    """The defect #354 names: the identity is per routine, and had no class in it."""
    artefact = bodies.findings(
        [_diagnosis("42P01", 'relation "tmp_orders" does not exist')], {}, temp=TEMP
    )
    baseline = Baseline.from_violations(artefact)

    real = bodies.findings([_diagnosis("42703", 'column "total" does not exist')], {}, temp=TEMP)

    assert baseline.diff(real).new == real


def test_the_registry_holds_every_class_in_the_body_family() -> None:
    codes = {rule.code: rule for rule in LINT_RULES}

    for code in ("body_001", "body_003", "body_004", "body_005"):
        assert codes[code].family == "body", code


def test_selecting_one_artefact_class_runs_the_analysis_for_it_alone() -> None:
    config = linter_config(frozenset({"body_003"}), Threshold.ERROR)

    assert (config.check_bodies, config.check_body_classes) == (False, frozenset({"body_003"}))


def test_a_body_names_the_relations_it_creates_temp() -> None:
    sql = """
    CREATE FUNCTION app.load() RETURNS void LANGUAGE plpgsql AS $$
    BEGIN
        CREATE TEMP TABLE tmp_orders (id int);
        CREATE TEMPORARY TABLE Tmp_Lines AS SELECT 1 AS n;
        CREATE TABLE app.kept (id int);
    END
    $$;
    """

    assert references.temp_relations(sql) == frozenset({"tmp_orders", "tmp_lines"})
