#!/usr/bin/env python3
"""Write seeds for this example's schema through ``confiture.platform`` and nothing else.

The shape a seed generator takes: read the schema into the model, walk the tables
parents first, supply only the columns a writer may, respect what each promises,
and write files the applier and the prep-seed validator accept.

    python generate.py [OUT_DIR]      # default: db/seeds/prep
"""

import random
import sys
import uuid
from pathlib import Path

from confiture import platform

HERE = Path(__file__).resolve().parent
ROWS = {"tb_vendor": 4, "tb_product": 12}
WORDS = ["Acme", "Globex", "Initech", "O'Brien", "Umbrella", "Hooli", "Stark", "Tyrell"]


def value(model, table, column, rng, ids):
    """One value for *column*, drawn from what the schema says about it."""
    facts = platform.column_facts(model, table, column.name)
    if facts.foreign_key is not None:
        return rng.choice(ids[facts.foreign_key.table])
    if facts.enum_values is not None:
        return rng.choice(facts.enum_values)
    if facts.type_key == "uuid":
        return str(uuid.UUID(int=rng.getrandbits(128), version=4))
    if facts.type_key.startswith("numeric"):
        return f"{rng.uniform(1, 500):.2f}"  # every CHECK here reads "> 0"
    if facts.type_key.startswith("varchar("):
        width = int(facts.type_key.removeprefix("varchar(").rstrip(")"))
        return "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(width))
    return f"{rng.choice(WORDS)} {rng.choice(WORDS)}"


def main(out: Path) -> None:
    model = platform.parse_schema(HERE / "db" / "schema")
    rng = random.Random(42)
    ids = {}
    tables = [t for t in platform.dependency_order(model) if t.schema == "prep_seed"]
    for number, table in enumerate(tables, 1):
        columns = platform.writable_columns(model, table)
        rows = [
            {c.name: value(model, table, c, rng, ids) for c in columns}
            for _ in range(ROWS[table.name])
        ]
        ids[table] = [row["id"] for row in rows]
        # The first as INSERT, the rest as COPY: both load through `seed apply`.
        write = platform.write_insert_seed if number == 1 else platform.write_copy_seed
        path = out / f"{number}0_{table.name.removeprefix('tb_')}.sql"
        write(path, table, [c.name for c in columns], rows, model=model)
        print(f"{path.name}: {len(rows)} rows of {table.schema}.{table.name}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "db" / "seeds" / "prep")
