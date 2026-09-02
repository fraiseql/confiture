"""execute_file naming a real file outside the project root: refused, never read."""

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000029"
    name = "shape"

    def up(self) -> None:
        self.execute_file("../idempotency_shapes_outside.sql")

    def down(self) -> None:
        pass
