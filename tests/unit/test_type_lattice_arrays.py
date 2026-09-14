"""An array is not its element type — in ``ddl_walk`` and in ``type_lattice``.

The suffix was lost twice, and either loss alone is enough to make ``f(int[])``
and ``f(int)`` one function:

* ``core/ddl_walk.type_name`` read ``names`` and ``typmods`` and never looked at
  ``arrayBounds``, so ``int[]``, ``int4[]``, ``integer[]`` and ``int[][]`` all
  rendered ``int4``;
* ``type_lattice._TYPE_RE`` matched a trailing ``[]`` and discarded it, so
  ``canonical_type('integer[]')`` was ``'integer'``.

Both callers of ``type_name`` compose the two — ``replica/classifier.py`` and
``change_set/walker.py``, each spelled ``canonical_type(_type_name(...))`` over
an ``ALTER COLUMN … TYPE`` — so the loss was a live bug on the preflight path,
in the expensive direction: a column going ``varchar(50)`` -> ``text[]`` was
captured as ``text`` and reported as needing **no heap rewrite**. This module's
own docstring is the standard it failed: *"guessing in the cheap direction is
the failure this module exists to prevent."*

The rule for a dimension mismatch is deliberately blunt — ``UNKNOWN``, and a
rewrite — because confiture models no array conversions and an unmodelled change
must never read as safe.
"""

from __future__ import annotations

import pglast
import pytest

from confiture.core.ddl_walk import type_name
from confiture.core.type_lattice import (
    TypeChange,
    canonical_type,
    changes_rewrite_table,
    compare_types,
    parse_type,
)


def _column_type(sql: str):
    """The ``TypeName`` node of an ``ALTER COLUMN … TYPE`` statement."""
    stmt = pglast.parser.parse_sql(sql)[0].stmt
    return stmt.cmds[0].def_.typeName


class TestDdlWalkCarriesTheSuffix:
    @pytest.mark.parametrize(
        ("written", "rendered"),
        [
            ("text", "text"),
            ("text[]", "text[]"),
            ("integer[]", "int4[]"),
            ("int[]", "int4[]"),
            ("int4[]", "int4[]"),
            ("int[][]", "int4[][]"),
            ("varchar(50)[]", "varchar(50)[]"),
        ],
    )
    def test_type_name_renders_the_array_bounds(self, written: str, rendered: str) -> None:
        assert type_name(_column_type(f"ALTER TABLE t ALTER COLUMN c TYPE {written};")) == rendered


class TestCanonicalTypeKeepsTheSuffix:
    @pytest.mark.parametrize(
        ("raw", "canonical"),
        [
            ("integer", "integer"),
            ("integer[]", "integer[]"),
            ("int4[]", "integer[]"),
            ("text[]", "text[]"),
            ("numeric(10,2)[]", "numeric(10,2)[]"),
            ("int[][]", "integer[][]"),
            ("varchar(50)[]", "varchar(50)[]"),
        ],
    )
    def test_canonical_type_keeps_the_suffix(self, raw: str, canonical: str) -> None:
        assert canonical_type(raw) == canonical

    def test_parse_type_counts_the_dimensions(self) -> None:
        assert parse_type("int[][]").dimensions == 2
        assert parse_type("integer").dimensions == 0

    def test_the_composition_keeps_an_array_apart_from_its_element(self) -> None:
        """What the signature key is built from: the two must not agree."""
        element = canonical_type(type_name(_column_type("ALTER TABLE t ALTER COLUMN c TYPE int;")))
        array = canonical_type(type_name(_column_type("ALTER TABLE t ALTER COLUMN c TYPE int[];")))

        assert element != array


class TestAnArrayIsNeverTheCheapAnswer:
    def test_an_element_to_array_change_is_not_identical(self) -> None:
        assert compare_types("text", "text[]") is TypeChange.UNKNOWN

    def test_an_array_to_its_element_is_not_identical(self) -> None:
        assert compare_types("text[]", "text") is TypeChange.UNKNOWN

    def test_two_dimensions_are_not_one(self) -> None:
        assert compare_types("int[]", "int[][]") is TypeChange.UNKNOWN

    def test_the_same_array_is_identical(self) -> None:
        assert compare_types("int4[]", "integer[]") is TypeChange.IDENTICAL

    def test_a_dimension_change_rewrites_the_heap(self) -> None:
        assert changes_rewrite_table("text", "text[]") is True

    def test_the_string_exemption_does_not_reach_arrays(self) -> None:
        """``varchar -> text`` is binary-coercible; ``varchar[] -> text[]`` is not."""
        assert changes_rewrite_table("varchar(50)", "text") is False
        assert changes_rewrite_table("varchar(50)[]", "text[]") is True

    def test_the_same_array_needs_no_rewrite(self) -> None:
        assert changes_rewrite_table("int4[]", "integer[]") is False


class TestTheScalarAnswersAreUnmoved:
    """The lattice's existing answers are what they were; only arrays move."""

    @pytest.mark.parametrize(
        ("old", "new", "expected"),
        [
            ("int", "bigint", TypeChange.WIDENING),
            ("bigint", "integer", TypeChange.NARROWING),
            ("integer", "int4", TypeChange.IDENTICAL),
            ("varchar(50)", "text", TypeChange.WIDENING),
        ],
    )
    def test_scalar_comparisons_are_unchanged(
        self, old: str, new: str, expected: TypeChange
    ) -> None:
        assert compare_types(old, new) is expected
