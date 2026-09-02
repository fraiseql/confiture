"""A class-attribute Path derived from a module constant, read through self."""

from pathlib import Path

from confiture.models.migration import Migration

_SCHEMA = Path(__file__).resolve().parent.parent / "schema"


class Shape(Migration):
    version = "20260101000034"
    name = "shape"
    _DIR = _SCHEMA

    def up(self) -> None:
        self.execute((self._DIR / "fn.sql").read_text())

    def down(self) -> None:
        pass
