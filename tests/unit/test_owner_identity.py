"""A configured role has one identity and one spelling, and every consumer compares the identity (#375).

``expected_owner: '"AppOwner"'`` is how the environment YAML spells a mixed-case
role: the SQL spelling. PostgreSQL holds the role as ``AppOwner`` — in
``pg_roles``, in ``pg_class.relowner``, and in the ``rolename`` pglast reads out of
``OWNER TO "AppOwner"``. Four consumers compared the quoted spelling with that
identity: bootstrap planned ``CREATE ROLE`` on every run, own_001 flagged every
object, the fixer never recognised the line it wrote, and drift reported every
relation as owned by the wrong role.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from confiture.config.environment import OwnershipApplyTo, OwnershipExpectation
from confiture.core.bootstrap import BootstrapPlanner
from confiture.core.linting.libraries.ownership import Own001OwnershipCoverage
from confiture.core.ownership_fixer import OwnershipFixer
from confiture.core.schema_identity import identifier_identity

MIGRATION = "20260527090000_add_foo.up.sql"


def _expectation(owner: str = '"AppOwner"') -> OwnershipExpectation:
    return OwnershipExpectation(
        expected_owner=owner,
        apply_to=[OwnershipApplyTo(schema="public", relkinds=["r", "S", "v", "m"])],
    )


@pytest.mark.parametrize(
    ("written", "identity"),
    [('"AppOwner"', "AppOwner"), ("app_owner", "app_owner"), ("AppOwner", "appowner")],
)
def test_an_identifier_is_what_postgresql_holds(written: str, identity: str) -> None:
    assert identifier_identity(written) == identity


def test_the_expectation_has_an_identity_and_a_spelling() -> None:
    expectation = _expectation()
    assert (expectation.owner_identity, expectation.owner_spelling) == (
        "AppOwner",
        '"AppOwner"',
    )


def test_own_001_accepts_an_owner_to_the_mixed_case_role(tmp_path: Path) -> None:
    (tmp_path / MIGRATION).write_text(
        'CREATE TABLE public.foo (id int);\nALTER TABLE public.foo OWNER TO "AppOwner";\n'
    )
    assert Own001OwnershipCoverage(expectation=_expectation()).check(tmp_path) == []


def test_own_001_accepts_a_run_as_directive_naming_it(tmp_path: Path) -> None:
    (tmp_path / MIGRATION).write_text(
        '-- confiture:run-as "AppOwner"\nCREATE TABLE public.foo (id int);\n'
    )
    assert Own001OwnershipCoverage(expectation=_expectation()).check(tmp_path) == []


def test_the_fixer_recognises_the_line_it_wrote(tmp_path: Path) -> None:
    path = tmp_path / MIGRATION
    path.write_text("CREATE TABLE public.foo (id int);\n")
    fixer = OwnershipFixer(expectation=_expectation())
    first = fixer.fix_text(path.read_text())
    path.write_text(first)
    assert 'OWNER TO "AppOwner";' in first
    assert fixer.fix_text(first) == first
    assert list(fixer.iter_candidates(tmp_path)) == []


def test_bootstrap_probes_pg_roles_for_the_role_itself() -> None:
    conn = MagicMock()
    probes: list[tuple] = []

    def execute(query: str, params: tuple | None = None) -> MagicMock:
        result = MagicMock()
        if "pg_roles" in query and params:
            probes.append(params)
            result.fetchone.return_value = (1,) if params == ("AppOwner",) else None
        else:
            result.fetchall.return_value = []
        return result

    conn.execute.side_effect = execute
    plan = BootstrapPlanner(ownership=_expectation()).plan(conn)
    assert probes == [("AppOwner",)]
    assert plan.is_empty
