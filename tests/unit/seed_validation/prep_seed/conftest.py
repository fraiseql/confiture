"""Shared helpers for the prep-seed level tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from confiture.core.schema_sources import read_schema
from confiture.core.seed.validation.prep_seed.resolvers import Resolver, find_resolvers


def _resolver(name: str) -> Resolver:
    ddl = f"CREATE FUNCTION {name}() RETURNS void AS $$ BEGIN PERFORM 1; END; $$ LANGUAGE plpgsql;"
    (resolver,) = find_resolvers(read_schema(ddl), catalog_schema="catalog")
    return resolver


@pytest.fixture
def resolver_of() -> Callable[[str], Resolver]:
    """The one resolver a ``CREATE FUNCTION <name>()`` defines, from DDL text."""
    return _resolver


@pytest.fixture
def manufacturer_resolver() -> Resolver:
    return _resolver("fn_resolve_tb_manufacturer")
