"""Pure string operations on static inputs: replace, format, dedent, strip (D9)."""

from textwrap import dedent

from confiture.models.migration import Migration

_TEMPLATE = "CREATE TABLE IF NOT EXISTS __T__ (id int)"
DDL = _TEMPLATE.replace("__T__", "a")


class Shape(Migration):
    version = "20260101000016"
    name = "shape"

    def up(self) -> None:
        self.execute(DDL)
        self.execute("CREATE TABLE IF NOT EXISTS {} (id int)".format("b"))
        self.execute(
            dedent(
                """
                CREATE TABLE IF NOT EXISTS c (id int)
                """
            ).strip()
        )

    def down(self) -> None:
        pass
