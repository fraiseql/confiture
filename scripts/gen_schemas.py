#!/usr/bin/env python3
"""Keep ``docs/reference/json-schemas/`` a byte-identical copy of the packaged schemas.

uv run python scripts/gen_schemas.py          # write the docs copy
uv run python scripts/gen_schemas.py --check  # exit 1 if the copy is stale (CI)
"""

from __future__ import annotations

import sys
from pathlib import Path

from confiture.core.schema_exporter import docs_out_of_sync, sync_docs

DOCS = Path(__file__).resolve().parents[1] / "docs" / "reference" / "json-schemas"


def main(argv: list[str]) -> int:
    if "--check" in argv:
        stale = docs_out_of_sync(DOCS)
        if stale:
            print("docs/reference/json-schemas is out of sync with python/confiture/schemas:")
            for name in stale:
                print(f"  {name}")
            print("run: uv run python scripts/gen_schemas.py")
            return 1
        print("docs/reference/json-schemas is in sync")
        return 0
    written = sync_docs(DOCS)
    print(f"wrote {len(written)} schema files to {DOCS}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
