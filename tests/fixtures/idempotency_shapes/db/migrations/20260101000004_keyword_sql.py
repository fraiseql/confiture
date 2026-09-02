"""The keyword form, sql=..."""

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000004"
    name = "shape"

    def up(self) -> None:
        self.execute(sql="CREATE TABLE IF NOT EXISTS a (id int)")

    def down(self) -> None:
        pass
