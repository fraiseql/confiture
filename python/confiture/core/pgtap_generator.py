"""Generate pgTAP test scaffolds from PostgreSQL functions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psycopg

from confiture.core.introspection.functions import FunctionIntrospector
from confiture.models.pgtap_models import PgTAPFile, PgTAPTest

if TYPE_CHECKING:
    pass


class PgTAPGenerator:
    """Generates pgTAP test scaffolds from a PostgreSQL schema's functions."""

    def __init__(
        self,
        connection: psycopg.Connection,
        schema: str = "public",
        *,
        name_pattern: str | None = None,
        include_volatility: bool = True,
        include_return_type: bool = True,
    ) -> None:
        self._conn = connection
        self._schema = schema
        self._name_pattern = name_pattern
        self._include_volatility = include_volatility
        self._include_return_type = include_return_type
        self._introspector = FunctionIntrospector(connection)

    def generate(self) -> PgTAPFile:
        """Introspect the schema and return a PgTAPFile ready to render."""
        catalog = self._introspector.introspect(
            self._schema,
            name_pattern=self._name_pattern,
        )
        db_name = catalog.database
        tests: list[PgTAPTest] = []

        for func in catalog.functions:
            # Always add existence test
            tests.append(PgTAPTest.function_exists(func))

            # Optionally add return type test
            if self._include_return_type and func.return_type:
                tests.append(PgTAPTest.function_returns(func))

            # Optionally add volatility test
            if self._include_volatility:
                tests.append(PgTAPTest.function_volatility(func))

        return PgTAPFile(
            schema=self._schema,
            database=db_name,
            generated_at=datetime.now(UTC).isoformat(),
            tests=tests,
            function_count=len(catalog.functions),
        )
