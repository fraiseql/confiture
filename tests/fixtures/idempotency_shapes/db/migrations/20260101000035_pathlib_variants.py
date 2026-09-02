"""pathlib.Path spelled out, parents[N], joinpath, resolve(): all the same path."""

import pathlib

from confiture.models.migration import Migration

_ROOT = pathlib.Path(__file__).parents[2]


class Shape(Migration):
    version = "20260101000035"
    name = "shape"

    def up(self) -> None:
        self.execute(_ROOT.joinpath("db", "schema", "fn.sql").resolve().read_text())

    def down(self) -> None:
        pass
