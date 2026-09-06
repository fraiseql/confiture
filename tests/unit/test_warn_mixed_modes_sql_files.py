"""The mixed-mode warning loads ``.up.sql`` migrations like everything else.

It used to import each file as a Python module, so a SQL-file migration in the
batch made the check itself fail.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

from confiture.core._migrator.engine import Migrator


def test_warns_about_a_mixed_batch_with_a_sql_file(tmp_path: Path, caplog) -> None:
    (tmp_path / "001_trans.py").write_text(
        "from confiture.models.migration import Migration\n"
        "class Trans(Migration):\n"
        "    version = '001'\n    name = 'trans'\n"
        "    def up(self): pass\n    def down(self): pass\n"
    )
    (tmp_path / "002_concurrent.up.sql").write_text("CREATE INDEX CONCURRENTLY idx_t ON t (a);\n")
    (tmp_path / "002_concurrent.down.sql").write_text("DROP INDEX idx_t;\n")

    migrator = Migrator(connection=MagicMock())
    with caplog.at_level(logging.WARNING):
        migrator._warn_mixed_transactional_modes(
            [tmp_path / "001_trans.py", tmp_path / "002_concurrent.up.sql"]
        )

    assert any("002_concurrent.up.sql" in r.getMessage() for r in caplog.records), caplog.text
