"""A loop target shadows a module constant of the same name inside up(): refused."""

from confiture.models.migration import Migration

DDL = "CREATE TABLE IF NOT EXISTS a (id int)"


class Shape(Migration):
    version = "20260101000023"
    name = "shape"

    def up(self) -> None:
        for DDL in ("CREATE TABLE IF NOT EXISTS b (id int)",):
            self.execute(DDL)

    def down(self) -> None:
        pass
