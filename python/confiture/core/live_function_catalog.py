"""Adapter that converts FunctionIntrospector results to FunctionSignature objects.

Bridges the existing introspection layer (FunctionIntrospector → FunctionInfo)
with the signature comparison layer (FunctionSignature from function_signature_parser).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from confiture.core.function_signature_parser import FunctionSignature, FunctionSignatureParser
from confiture.core.introspection.functions import FunctionIntrospector
from confiture.models.function_info import ParamMode

if TYPE_CHECKING:
    import psycopg


class LiveFunctionCatalog:
    """Query live DB function signatures via FunctionIntrospector.

    Each PostgreSQL overload appears as a separate FunctionSignature entry.
    Only IN and INOUT parameters are included in param_types, matching the
    PostgreSQL overload resolution key.

    Args:
        connection: An open psycopg connection to the target database.

    Example:
        catalog = LiveFunctionCatalog(conn)
        sigs = catalog.get_signatures(schemas=["public", "auth"])
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._conn = connection
        self._introspector = FunctionIntrospector(connection)
        self._parser = FunctionSignatureParser()

    def get_signatures(self, schemas: list[str] | None = None) -> list[FunctionSignature]:
        """Return FunctionSignature for every IN/INOUT overload in the given schemas.

        Args:
            schemas: Schema names to query (default: ["public"])

        Returns:
            One FunctionSignature per overload (same function may appear multiple times
            if it has different parameter type combinations in the live DB).
        """
        schemas = schemas or ["public"]
        result: list[FunctionSignature] = []

        for schema in schemas:
            catalog = self._introspector.introspect(schema=schema)
            for fn in catalog.functions:
                param_types = tuple(
                    self._parser._normalise_type(p.pg_type)
                    for p in fn.params
                    if p.mode in (ParamMode.IN, ParamMode.INOUT)
                )
                result.append(
                    FunctionSignature(
                        schema=fn.schema,
                        name=fn.name,
                        param_types=param_types,
                    )
                )

        return result
