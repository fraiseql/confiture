"""A string literal at the call site: the shape everything else is measured against."""

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000001"
    name = "shape"

    def up(self) -> None:
        self.execute("CREATE TABLE IF NOT EXISTS a (id int)")

    def down(self) -> None:
        pass
