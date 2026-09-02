"""A class attribute read through self."""

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000011"
    name = "shape"
    _SQL = "CREATE TABLE IF NOT EXISTS a (id int)"

    def up(self) -> None:
        self.execute(self._SQL)

    def down(self) -> None:
        pass
