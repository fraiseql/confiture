"""Generate typed Python wrapper stubs from PostgreSQL functions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psycopg

from confiture.core.introspection.functions import FunctionIntrospector
from confiture.core.introspection.type_mapping import TypeMapper
from confiture.models.stub_models import StubFile, StubFunction

if TYPE_CHECKING:
    pass


class StubGenerator:
    """Generates typed Python stubs from a PostgreSQL schema's functions."""

    def __init__(
        self,
        connection: psycopg.Connection,
        schema: str = "public",
        *,
        include_triggers: bool = False,
        name_pattern: str | None = None,
        mapper: TypeMapper | None = None,
    ) -> None:
        self._conn = connection
        self._schema = schema
        self._introspector = FunctionIntrospector(connection)
        self._mapper = mapper or TypeMapper()
        self._include_triggers = include_triggers
        self._name_pattern = name_pattern

    def generate(self) -> StubFile:
        """Introspect the schema and return a StubFile ready to render."""
        catalog = self._introspector.introspect(
            self._schema,
            include_triggers=self._include_triggers,
            name_pattern=self._name_pattern,
        )
        db_name = catalog.database
        functions = [StubFunction.from_function_info(f, self._mapper) for f in catalog.functions]
        all_imports: set[str] = set()
        for fn in functions:
            all_imports |= fn.required_imports

        return StubFile(
            schema=self._schema,
            database=db_name,
            generated_at=datetime.now(UTC).isoformat(),
            functions=functions,
            imports=all_imports,
        )
