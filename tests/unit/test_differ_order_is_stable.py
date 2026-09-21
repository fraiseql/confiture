"""A diff lists its changes in one order, whatever the interpreter's hash seed.

Enum types and sequences were emitted in ``set`` iteration order, and a ``str``
hash is randomised per process: two added enum types came out ``mood,
new_status`` on one run and ``new_status, mood`` on the next, so ``migrate diff
--generate`` wrote a different migration from the same two trees. The order is
the one tables already had — by identity.
"""

from __future__ import annotations

import json
import subprocess
import sys

_SCRIPT = """
import json
from confiture.core.differ import SchemaDiffer

old = "CREATE TYPE gone_a AS ENUM ('x'); CREATE TYPE gone_b AS ENUM ('x');" \\
      " CREATE SEQUENCE gone_s1; CREATE SEQUENCE gone_s2;"
new = "CREATE TYPE mood AS ENUM ('a'); CREATE TYPE new_status AS ENUM ('b');" \\
      " CREATE TYPE zeta AS ENUM ('c'); CREATE SEQUENCE s_one; CREATE SEQUENCE s_two;"
print(json.dumps([str(change) for change in SchemaDiffer().compare(old, new).changes]))
"""


def _changes(seed: int) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        env={"PYTHONHASHSEED": str(seed), "PATH": ""},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_enum_types_and_sequences_are_listed_in_one_order_whatever_the_seed() -> None:
    orders = {tuple(_changes(seed)) for seed in range(8)}
    assert orders == {
        (
            "ADD ENUM TYPE mood",
            "ADD ENUM TYPE new_status",
            "ADD ENUM TYPE zeta",
            "DROP ENUM TYPE gone_a",
            "DROP ENUM TYPE gone_b",
            "ADD SEQUENCE s_one",
            "ADD SEQUENCE s_two",
            "DROP SEQUENCE gone_s1",
            "DROP SEQUENCE gone_s2",
        )
    }
