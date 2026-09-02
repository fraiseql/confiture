"""A module-level reader helper with *parts."""

from pathlib import Path

from confiture.models.migration import Migration

_SCHEMA = Path(__file__).resolve().parent.parent / "schema"


def _read_sql(*parts: str) -> str:
    return (_SCHEMA / Path(*parts)).read_text()


class Shape(Migration):
    version = "20260101000014"
    name = "shape"

    def up(self) -> None:
        self.execute(_read_sql("fn.sql"))

    def down(self) -> None:
        pass
