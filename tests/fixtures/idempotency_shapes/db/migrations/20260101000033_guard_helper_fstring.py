"""A one-line f-string wrapper helper around a constant."""

from confiture.models.migration import Migration

DDL = "CREATE TABLE IF NOT EXISTS a (id int)"


def _guard(sql: str) -> str:
    return f"DO $$ BEGIN {sql}; END $$"


class Shape(Migration):
    version = "20260101000033"
    name = "shape"

    def up(self) -> None:
        self.execute(_guard(DDL))

    def down(self) -> None:
        pass
