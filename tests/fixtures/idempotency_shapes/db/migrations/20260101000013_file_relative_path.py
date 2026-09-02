"""Path arithmetic from __file__: the corpus's dominant file-read shape."""

from pathlib import Path

from confiture.models.migration import Migration

_SCHEMA = Path(__file__).resolve().parent.parent / "schema"


class Shape(Migration):
    version = "20260101000013"
    name = "shape"

    def up(self) -> None:
        self.execute((_SCHEMA / "fn.sql").read_text())

    def down(self) -> None:
        pass
