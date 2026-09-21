"""Where naming an exit changed what a command exits with.

Naming each exit made three commands visible that disagreed with the registry
about the same situation — a missing config file exits 5 (CONFIG_004)
everywhere else — or with themselves across output formats.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.seed.bridge import SeedGenerationResult

runner = CliRunner()


def test_seed_generate_failure_exits_1_in_json_too(tmp_path: Path) -> None:
    """The result carries the failure in both formats; JSON exited 0 on it until 1.16."""
    failed = SeedGenerationResult(
        table="t",
        output_path=tmp_path / "t.sql",
        row_count=0,
        column_count=0,
        success=False,
        error="no such table",
    )
    bridge = MagicMock()
    bridge.generate.return_value = failed
    with patch("confiture.cli.seed.SeedBridge", return_value=bridge):
        result = runner.invoke(
            app,
            ["seed", "generate", "t", "-d", "postgresql://localhost/x", "--format", "json"],
        )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["success"] is False
