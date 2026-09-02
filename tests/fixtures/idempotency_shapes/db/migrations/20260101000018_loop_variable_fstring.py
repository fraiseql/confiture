"""An f-string over a loop variable: genuinely dynamic, never resolved (D8)."""

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000018"
    name = "shape"

    def up(self) -> None:
        for table in ("a", "b"):
            self.execute(f"CREATE TABLE IF NOT EXISTS {table} (id int)")

    def down(self) -> None:
        pass
