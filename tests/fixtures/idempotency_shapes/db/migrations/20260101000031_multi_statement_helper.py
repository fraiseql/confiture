"""A reader helper with more than one statement: refused."""

from pathlib import Path

from confiture.models.migration import Migration

_SCHEMA = Path(__file__).resolve().parent.parent / "schema"


def _read_sql(name: str) -> str:
    text = (_SCHEMA / name).read_text()
    return text.strip()


class Shape(Migration):
    version = "20260101000031"
    name = "shape"

    def up(self) -> None:
        self.execute(_read_sql("fn.sql"))

    def down(self) -> None:
        pass
