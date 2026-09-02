"""The SQL arrives as a parameter: refused."""

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000019"
    name = "shape"

    def _apply(self, sql: str) -> None:
        self.execute(sql)

    def up(self) -> None:
        self._apply("CREATE TABLE IF NOT EXISTS a (id int)")

    def down(self) -> None:
        pass
