"""Augmented assignment is a second binding: refused."""

from confiture.models.migration import Migration

DDL = "CREATE TABLE "
DDL += "IF NOT EXISTS a (id int)"


class Shape(Migration):
    version = "20260101000021"
    name = "shape"

    def up(self) -> None:
        self.execute(DDL)

    def down(self) -> None:
        pass
