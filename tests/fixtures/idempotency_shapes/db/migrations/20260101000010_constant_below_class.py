"""A constant defined below the class: bound by the time up() runs."""

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000010"
    name = "shape"

    def up(self) -> None:
        self.execute(DDL)

    def down(self) -> None:
        pass


DDL = "CREATE TABLE IF NOT EXISTS a (id int)"
