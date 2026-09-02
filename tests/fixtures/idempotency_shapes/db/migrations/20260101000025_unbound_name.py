"""A name bound nowhere in the file: refused."""

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000025"
    name = "shape"

    def up(self) -> None:
        self.execute(sql)

    def down(self) -> None:
        pass
