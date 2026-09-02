"""A reader helper that is a method, reading a class-attribute directory."""

from pathlib import Path

from confiture.models.migration import Migration

_SCHEMA = Path(__file__).resolve().parent.parent / "schema"


class Shape(Migration):
    version = "20260101000015"
    name = "shape"
    _DIR = _SCHEMA

    def _sql(self, name: str) -> str:
        return (self._DIR / name).read_text()

    def up(self) -> None:
        self.execute(self._sql("fn.sql"))

    def down(self) -> None:
        pass
