"""An f-string whose only placeholder is a single-assignment local string."""

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000017"
    name = "shape"

    def up(self) -> None:
        table = "a"
        self.execute(f"CREATE TABLE IF NOT EXISTS {table} (id int)")

    def down(self) -> None:
        pass
