"""An f-string placeholder with a conversion (!r): refused."""

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000032"
    name = "shape"

    def up(self) -> None:
        table = "a"
        self.execute(f"CREATE TABLE IF NOT EXISTS {table!r} (id int)")

    def down(self) -> None:
        pass
