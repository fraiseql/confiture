"""Drift is the one comparison said as findings: ``drift.DRIFT_OF`` answers for every change.

``confiture drift`` once had a comparison of its own beside the differ's, and the
two disagreed (a primary key, a foreign key's action, a default's value were
drift's alone). Now drift asks the differ and says what it answers. This module
holds the table that says it: every variant of the change union is a finding of a
stated kind and severity, or names why drift has none — and every schema drift
kind is reached from it, so none is reported by a comparison of drift's own.
"""

import ast
from pathlib import Path

import confiture
from confiture.core.drift import _OBJECT_DRIFT_TYPES, DRIFT_OF, REDEFINED_DRIFT_TYPES, DriftType
from confiture.core.schema_change import KINDS

DRIFT = Path(confiture.__file__).resolve().parent / "core" / "drift.py"

#: The kinds another detector reports: grants and owners are not schema facts.
_NOT_THE_SCHEMAS = {DriftType.MISSING_GRANT, DriftType.EXTRA_GRANT, DriftType.WRONG_OWNER}


def test_every_change_is_a_finding_or_says_why_not() -> None:
    assert set(DRIFT_OF) == set(KINDS)
    reasons = [why for why in DRIFT_OF.values() if isinstance(why, str)]
    assert all(why.strip() for why in reasons)


def test_every_schema_drift_kind_is_reached_from_the_table() -> None:
    reached = {kind for kind, _ in (v for v in DRIFT_OF.values() if not isinstance(v, str))}
    reached |= {kind for pair in _OBJECT_DRIFT_TYPES.values() for kind in pair}
    reached |= set(REDEFINED_DRIFT_TYPES.values())
    # A constraint dropped and added under one name is one finding.
    reached.add(DriftType.CONSTRAINT_MISMATCH)
    assert set(DriftType) - _NOT_THE_SCHEMAS == reached - {None}


def test_drift_compares_nothing_itself() -> None:
    """No ``_compare_*`` and no ``_same_*``: a second comparison is how they disagreed."""
    defined = {
        node.name
        for node in ast.walk(ast.parse(DRIFT.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef)
    }
    assert sorted(n for n in defined if n.startswith(("_compare_", "_same_"))) == []


def test_matview_index_changes_are_rendered() -> None:
    """An index change on a matview both models hold is a finding on that matview."""
    from dataclasses import replace

    from confiture.core.drift import DriftReport, DriftSeverity, _Findings
    from confiture.core.schema_change import IndexAdded
    from confiture.core.schema_model import ref_for
    from confiture.core.schema_read import read_text

    view = "CREATE TABLE t (id int);\nCREATE MATERIALIZED VIEW mv AS SELECT id FROM t;\n"
    expected = read_text(view + "CREATE UNIQUE INDEX ux_mv ON mv (id);\n").catalogued
    actual = replace(read_text(view).catalogued, source="catalog")
    (index,) = expected.views[ref_for("matview", None, "mv")].indexes
    report = DriftReport(database_name="db", expected_schema_source="tree")
    _Findings(expected, actual, DriftSeverity.WARNING).render(
        [IndexAdded(index.table, index, relation_kind="matview")], report, column_order=False
    )
    (item,) = report.drift_items
    assert (item.drift_type, item.severity) == (DriftType.MISSING_INDEX, DriftSeverity.CRITICAL)
    assert item.object_name == "public.mv.ux_mv"
    assert report.indexes_checked == 1


def test_a_redefined_matviews_index_changes_are_rendered() -> None:
    """A redefined matview is its query's finding; the index changes it carries are, as a paired one's."""
    from dataclasses import replace

    from confiture.core.drift import DriftReport, DriftSeverity, _Findings
    from confiture.core.schema_change import IndexAdded, ObjectReplaced
    from confiture.core.schema_model import ref_for
    from confiture.core.schema_read import read_text

    table = "CREATE TABLE t (id int);\n"
    query = "CREATE MATERIALIZED VIEW mv AS SELECT id FROM t;\n"
    other = "CREATE MATERIALIZED VIEW mv AS SELECT id FROM t WHERE id > 0;\n"
    mv = ref_for("matview", None, "mv")
    tree = read_text(table + other + "CREATE UNIQUE INDEX ux_mv ON mv (id);\n")
    database = read_text(table + query)
    (index,) = tree.catalogued.views[mv].indexes
    change = ObjectReplaced(
        mv,
        database.declared.objects[mv][0],
        tree.declared.objects[mv][0],
        index_changes=(IndexAdded(index.table, index, relation_kind="matview"),),
    )
    report = DriftReport(database_name="db", expected_schema_source="tree")
    _Findings(
        tree.catalogued, replace(database.catalogued, source="catalog"), DriftSeverity.WARNING
    ).render([change], report, column_order=False)
    index, query = report.drift_items
    assert (index.drift_type, index.severity) == (DriftType.MISSING_INDEX, DriftSeverity.CRITICAL)
    assert index.object_name == "public.mv.ux_mv"
    assert (query.drift_type, query.severity) == (
        DriftType.VIEW_DEFINITION_MISMATCH,
        DriftSeverity.WARNING,
    )


def test_every_redefinition_drift_does_not_render_says_why() -> None:
    """A TVIEW's is its options, a view's its query (#719); a routine's body is named, with the reason."""
    from confiture.core.differ import _SECTIONS
    from confiture.core.drift import UNRENDERED_REDEFINITIONS

    routines = {kind for kind, section in _SECTIONS.items() if section == "routines"}
    assert set(UNRENDERED_REDEFINITIONS) == routines
    assert routines == {"function", "procedure", "aggregate"}
    views = {kind for kind, section in _SECTIONS.items() if section == "views"}
    assert views == {"view", "matview"}
    assert all(REDEFINED_DRIFT_TYPES[kind] is DriftType.VIEW_DEFINITION_MISMATCH for kind in views)
    assert all(why.strip() for why in UNRENDERED_REDEFINITIONS.values())


def test_a_redefinition_is_a_finding_or_says_why_not_never_both() -> None:
    """A domain's redefinition is never a TVIEW's finding, nor a view's silence (#708)."""
    from confiture.core.drift import UNRENDERED_REDEFINITIONS
    from confiture.core.schema_model import DEFINED_OTHER_KINDS

    assert not set(REDEFINED_DRIFT_TYPES) & set(UNRENDERED_REDEFINITIONS)
    assert set(REDEFINED_DRIFT_TYPES) == {"tview", "view", "matview", *DEFINED_OTHER_KINDS}
    assert {
        kind
        for kind, found in REDEFINED_DRIFT_TYPES.items()
        if found is DriftType.TVIEW_OPTION_MISMATCH
    } == {"tview"}


def test_drift_meets_a_domain_redefined_only_as_its_tier_reads_it() -> None:
    """Against a database, a trigger is compared by existence and a domain by what it is.

    Drift's policies carry parity rules, under which a trigger whose statement
    differs is the same trigger. A domain is read whole (#708): a CHECK whose text
    alone changed is the same domain when expressions compare by presence
    (``CATALOGUED``) and another one when both sides are PostgreSQL's reading
    (``MATERIALISED``).
    """
    from dataclasses import replace

    from confiture.core.differ import CATALOGUED, MATERIALISED, SchemaDiffer, Side
    from confiture.core.schema_change import ObjectReplaced
    from confiture.core.schema_model import Coverage
    from confiture.core.schema_read import read_text

    base = "CREATE TABLE t (id int);\nCREATE FUNCTION f() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;\n"
    before = read_text(
        base
        + "CREATE TRIGGER trg BEFORE INSERT ON t FOR EACH ROW EXECUTE FUNCTION f();\n"
        + "CREATE DOMAIN d AS int CHECK (VALUE > 0);\n"
    )
    after = read_text(
        base
        + "CREATE TRIGGER trg BEFORE UPDATE ON t FOR EACH ROW EXECUTE FUNCTION f();\n"
        + "CREATE DOMAIN d AS int CHECK (VALUE > 1);\n"
    )
    # The control: two trees compare every statement as written, so both differ.
    kinds = {
        c.ref.kind for c in SchemaDiffer().compare_sides(Side.of(before), Side.of(after)).changes
    }
    assert kinds == {"trigger", "domain"}
    read = dict(before.catalogued.coverage.sections)
    coverage = Coverage.of({**read, "other_objects": "existence"})
    database = Side(
        replace(before.catalogued, source="catalog", coverage=coverage), before.declared.objects
    )
    for policy, redefined in ((CATALOGUED, set()), (MATERIALISED, {"domain"})):
        changes = SchemaDiffer().compare_sides(database, Side.of(after, held=True), policy)
        replaced = {c.ref.kind for c in changes.changes if isinstance(c, ObjectReplaced)}
        assert replaced == redefined, policy.name


def test_tview_index_changes_are_rendered() -> None:
    """An index change on a TVIEW both models hold is a finding on that TVIEW."""
    from dataclasses import replace

    from confiture.core.drift import DriftReport, DriftSeverity, _Findings
    from confiture.core.schema_change import IndexAdded, IndexDropped
    from confiture.core.schema_model import ref_for
    from confiture.core.schema_read import read_text

    tview = "CREATE TABLE t (id int);\nCREATE TABLE tv_t AS SELECT id FROM t;\n"
    expected = read_text(tview + "CREATE UNIQUE INDEX ux_tv_t ON tv_t (id);\n").catalogued
    actual = read_text(tview + "CREATE INDEX ix_tv_t ON tv_t (id);\n").catalogued
    actual = replace(actual, source="catalog")
    ref = ref_for("tview", None, "tv_t")
    (missing,) = expected.tviews[ref].indexes or ()
    (extra,) = actual.tviews[ref].indexes or ()
    report = DriftReport(database_name="db", expected_schema_source="tree")
    _Findings(expected, actual, DriftSeverity.WARNING).render(
        [
            IndexAdded(missing.table, missing, relation_kind="tview"),
            IndexDropped(extra.table, extra, relation_kind="tview"),
        ],
        report,
        column_order=False,
    )
    found = {(i.drift_type, i.severity, i.object_name) for i in report.drift_items}
    assert found == {
        (DriftType.MISSING_INDEX, DriftSeverity.CRITICAL, "public.tv_t.ux_tv_t"),
        (DriftType.EXTRA_INDEX, DriftSeverity.INFO, "public.tv_t.ix_tv_t"),
    }
    assert report.indexes_checked == 2


def test_tview_indexes_not_read_are_no_finding() -> None:
    """A side whose TVIEW indexes were not read says nothing about them."""
    from dataclasses import replace

    from confiture.core.drift import DriftReport, DriftSeverity, _Findings
    from confiture.core.schema_change import IndexAdded
    from confiture.core.schema_model import ref_for
    from confiture.core.schema_read import read_text

    tview = "CREATE TABLE t (id int);\nCREATE TABLE tv_t AS SELECT id FROM t;\n"
    expected = read_text(tview + "CREATE UNIQUE INDEX ux_tv_t ON tv_t (id);\n").catalogued
    ref = ref_for("tview", None, "tv_t")
    actual = read_text(tview).catalogued
    actual = replace(
        actual,
        source="catalog",
        tviews={ref: replace(actual.tviews[ref], indexes=None)},
    )
    (missing,) = expected.tviews[ref].indexes or ()
    report = DriftReport(database_name="db", expected_schema_source="tree")
    _Findings(expected, actual, DriftSeverity.WARNING).render(
        [IndexAdded(missing.table, missing, relation_kind="tview")], report, column_order=False
    )
    assert report.drift_items == []
