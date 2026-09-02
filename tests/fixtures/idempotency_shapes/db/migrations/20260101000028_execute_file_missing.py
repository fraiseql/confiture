"""execute_file naming a file that does not exist anywhere."""

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000028"
    name = "shape"

    def up(self) -> None:
        self.execute_file("db/schema/nope.sql")

    def down(self) -> None:
        pass
