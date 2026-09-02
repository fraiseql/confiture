"""Path(<literal>).read_text() inside execute (#185)."""

from pathlib import Path

from confiture.models.migration import Migration


class Shape(Migration):
    version = "20260101000006"
    name = "shape"

    def up(self) -> None:
        self.execute(Path("db/schema/fn.sql").read_text())

    def down(self) -> None:
        pass
