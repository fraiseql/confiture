"""An annotated module constant (Final) resolves like a bare one."""

from typing import Final

from confiture.models.migration import Migration

DDL: Final[str] = "CREATE TABLE IF NOT EXISTS a (id int)"


class Shape(Migration):
    version = "20260101000009"
    name = "shape"

    def up(self) -> None:
        self.execute(DDL)

    def down(self) -> None:
        pass
