"""A method declares the name global and assigns it: refused."""

from confiture.models.migration import Migration

DDL = "CREATE TABLE IF NOT EXISTS a (id int)"


class Shape(Migration):
    version = "20260101000022"
    name = "shape"

    def up(self) -> None:
        self.execute(DDL)

    def down(self) -> None:
        global DDL
        DDL = "DROP TABLE IF EXISTS a"
        self.execute(DDL)
