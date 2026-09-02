"""An f-string with no placeholders is a literal."""

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000002"
    name = "shape"

    def up(self) -> None:
        self.execute("CREATE TABLE IF NOT EXISTS a (id int)")

    def down(self) -> None:
        pass
