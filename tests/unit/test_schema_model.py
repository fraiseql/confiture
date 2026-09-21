"""``core/schema_model.py``: the one model of what a schema declares.

A table, its columns and constraints, its indexes, an enum and a sequence are
each defined **once**, here, and every reader of a DDL tree — and, later, of a
live catalog — produces these types. The module is data and nothing else: it
imports no parser and no driver, so a tool that only wants to *hold* a schema
(a seed generator, a port's parity fixture) does not pay for either.
"""

from __future__ import annotations

import json
import subprocess
import sys

PROBE = """
import json, sys
import confiture.core.schema_model
print(json.dumps(sorted(m for m in ("pglast", "psycopg") if m in sys.modules)))
"""


def test_schema_model_is_import_safe() -> None:
    """Importing the model leaves pglast and psycopg unimported, in a fresh interpreter.

    A subprocess rather than an in-process check: by the time this test runs the
    suite has imported both.
    """
    out = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    ).stdout
    assert json.loads(out) == []
