"""Adapter that converts FunctionIntrospector results to FunctionSignature objects.

Bridges the existing introspection layer (FunctionIntrospector → FunctionInfo)
with the signature comparison layer (FunctionSignature from function_signature_parser).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from confiture.core.function_signature_parser import FunctionSignature, FunctionSignatureParser
from confiture.core.introspection.functions import FunctionIntrospector
from confiture.models.function_info import FunctionInfo, ParamMode

if TYPE_CHECKING:
    import psycopg

_NO_BODY_LANGUAGES = frozenset({"c", "internal"})


class LiveFunctionCatalog:
    """Query live DB function signatures via FunctionIntrospector.

    Each PostgreSQL overload appears as a separate FunctionSignature entry.
    Only IN and INOUT parameters are included in param_types, matching the
    PostgreSQL overload resolution key.

    Introspection results are cached on first load so that calling both
    ``get_signatures()`` and ``get_bodies()`` in the same invocation triggers
    only a single database query per schema.

    Args:
        connection: An open psycopg connection to the target database.

    Example:
        catalog = LiveFunctionCatalog(conn)
        sigs = catalog.get_signatures(schemas=["public", "auth"])
        bodies = catalog.get_bodies(schemas=["public", "auth"])
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._conn = connection
        self._introspector = FunctionIntrospector(connection)
        self._parser = FunctionSignatureParser()
        # Cache populated on first call; None = not yet loaded.
        self._fn_infos: list[FunctionInfo] | None = None

    def _load(self, schemas: list[str]) -> list[FunctionInfo]:
        """Fetch and cache FunctionInfo for *schemas*.

        Subsequent calls return the cached list regardless of *schemas*.
        The cache lifetime is the ``LiveFunctionCatalog`` instance, which is
        typically created once per ``migrate validate`` invocation.
        """
        if self._fn_infos is None:
            infos: list[FunctionInfo] = []
            for schema in schemas:
                catalog = self._introspector.introspect(schema=schema)
                infos.extend(catalog.functions)
            self._fn_infos = infos
        return self._fn_infos

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

        for fn in self._load(schemas):
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

    def get_bodies(
        self,
        schemas: list[str] | None = None,
        sig_keys: set[str] | None = None,
    ) -> dict[str, str | None]:
        """Return a mapping of signature_key → raw prosrc body.

        Functions with ``LANGUAGE c`` or ``LANGUAGE internal`` have no SQL body
        and are represented as ``None`` in the returned dict.

        Args:
            schemas: Schema names to query (default: ["public"]).
            sig_keys: Optional set of signature keys to restrict results.
                      When ``None``, bodies for all signatures in *schemas* are
                      returned.

        Returns:
            dict mapping ``signature_key`` strings to ``prosrc`` strings or
            ``None`` for C/internal functions.
        """
        schemas = schemas or ["public"]
        result: dict[str, str | None] = {}

        for fn in self._load(schemas):
            param_types = tuple(
                self._parser._normalise_type(p.pg_type)
                for p in fn.params
                if p.mode in (ParamMode.IN, ParamMode.INOUT)
            )
            sig = FunctionSignature(schema=fn.schema, name=fn.name, param_types=param_types)
            key = sig.signature_key()
            if sig_keys is not None and key not in sig_keys:
                continue
            result[key] = None if fn.language in _NO_BODY_LANGUAGES else fn.source

        return result
