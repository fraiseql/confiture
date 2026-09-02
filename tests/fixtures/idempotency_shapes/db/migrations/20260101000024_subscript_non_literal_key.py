"""A subscript with a non-literal key: refused."""

from confiture.models.migration import Migration

SQL = {"a": "CREATE TABLE IF NOT EXISTS a (id int)"}


class Shape(Migration):
    version = "20260101000024"
    name = "shape"

    def up(self) -> None:
        for key in SQL:
            self.execute(SQL[key])

    def down(self) -> None:
        pass
