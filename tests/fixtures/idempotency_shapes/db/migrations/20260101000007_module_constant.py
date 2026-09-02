"""The #213 repro: the SQL lives in a module-scope constant."""

from confiture.models.migration import Migration

DDL = "CREATE TABLE IF NOT EXISTS a (id int)"


class Shape(Migration):
    version = "20260101000007"
    name = "shape"

    def up(self) -> None:
        self.execute(DDL)

    def down(self) -> None:
        pass
