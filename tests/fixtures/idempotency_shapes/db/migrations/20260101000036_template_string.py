"""A template string is not a str: its SQL is whatever the runtime renders. Refused."""

from confiture.models.migration import Migration

TABLE = "a"


class Shape(Migration):
    version = "20260101000036"
    name = "shape"

    def up(self) -> None:
        self.execute(t"CREATE TABLE IF NOT EXISTS {TABLE:i} (id int)")

    def down(self) -> None:
        pass
