"""A function-local bound exactly once."""

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000012"
    name = "shape"

    def up(self) -> None:
        sql = "CREATE TABLE IF NOT EXISTS a (id int)"
        self.execute(sql)

    def down(self) -> None:
        pass
