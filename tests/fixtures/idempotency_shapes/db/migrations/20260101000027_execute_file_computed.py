"""execute_file with a computed Path."""

from pathlib import Path

from confiture.models.migration import Migration

_SCHEMA = Path(__file__).resolve().parent.parent / "schema"


class Shape(Migration):
    version = "20260101000027"
    name = "shape"

    def up(self) -> None:
        self.execute_file(_SCHEMA / "fn.sql")

    def down(self) -> None:
        pass
