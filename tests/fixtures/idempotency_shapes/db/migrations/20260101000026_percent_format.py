"""Percent formatting is outside the grammar (D9): refused."""

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000026"
    name = "shape"

    def up(self) -> None:
        self.execute("CREATE TABLE IF NOT EXISTS %s (id int)" % "a")

    def down(self) -> None:
        pass
