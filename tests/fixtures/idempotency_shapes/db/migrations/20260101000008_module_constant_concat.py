"""Constants built from other constants with +, and a literal + constant at the call."""

from confiture.models.migration import Migration

_HEAD = "CREATE TABLE "
_TAIL = "IF NOT EXISTS a (id int)"
DDL = _HEAD + _TAIL


class Shape(Migration):
    version = "20260101000008"
    name = "shape"

    def up(self) -> None:
        self.execute(DDL)
        self.execute("CREATE TABLE " + _TAIL)

    def down(self) -> None:
        pass
