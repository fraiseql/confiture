"""execute_file with a project-root-relative literal path."""

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000005"
    name = "shape"

    def up(self) -> None:
        self.execute_file("db/schema/fn.sql")

    def down(self) -> None:
        pass
