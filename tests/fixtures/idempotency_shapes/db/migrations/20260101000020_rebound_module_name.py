"""A module name bound twice: refused, whichever value wins at runtime."""

from confiture.models.migration import Migration

DDL = "CREATE TABLE IF NOT EXISTS a (id int)"
DDL = "CREATE TABLE IF NOT EXISTS b (id int)"


class Shape(Migration):
    version = "20260101000020"
    name = "shape"

    def up(self) -> None:
        self.execute(DDL)

    def down(self) -> None:
        pass
