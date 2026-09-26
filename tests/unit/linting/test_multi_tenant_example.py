"""``examples/09-multi-tenant-schema`` passes the whole ``tenant`` family, and each rule reads it.

The example is the design of ``docs/guides/multi-tenant-schemas.md`` as a project:
a ``tenancy:`` block, a global catalogue, a counterparty over a global directory of
companies, composite keys and foreign keys, a view publishing the discriminator, a
hybrid read view, and a routine whose ``INSERT`` supplies it. A clean run proves
nothing unless the rules actually read it, so each rule is also shown to fire on a
one-line edit of a copy.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "09-multi-tenant-schema"
FAMILY = ("tenant_001", "tenant_002", "tenant_003", "tenant_004", "tenant_005")


def _lint(project: Path) -> tuple[int, dict[str, Any]]:
    result = CliRunner().invoke(
        app, ["lint", "--project-dir", str(project), "--format", "json", "--fail-on", "info"]
    )
    return result.exit_code, json.loads(result.stdout)


def test_the_example_declares_tenancy() -> None:
    assert "tenancy:" in (EXAMPLE / "db" / "project.yaml").read_text()


def test_the_example_lints_clean_with_the_family_on() -> None:
    """Zero findings of any rule, at any severity, and nothing skipped or degraded."""
    code, payload = _lint(EXAMPLE)

    assert payload["violations"]["items"] == []
    assert payload["skipped"] == []
    assert payload["degraded"] == []
    assert code == 0


#: One edit per rule: (file under db/schema, text, replacement, the rule it trips).
_EDITS = [
    (
        "30_app/40_fn_create_order.sql",
        "INSERT INTO app.tb_order (tenant_id, id,",
        "INSERT INTO app.tb_order (id,",
        "tenant_001",
    ),
    (
        "30_app/10_tb_custom_unit.sql",
        "tenant_id uuid NOT NULL REFERENCES management.tb_organization (id),",
        "tenant_id uuid NOT NULL,",
        "tenant_002",
    ),
    ("30_app/50_v_order.sql", "SELECT o.tenant_id,", "SELECT", "tenant_003"),
    (
        "30_app/30_tb_order.sql",
        "FOREIGN KEY (tenant_id, fk_provider) REFERENCES app.tb_provider (tenant_id, id)",
        "FOREIGN KEY (fk_provider) REFERENCES app.tb_provider (id)",
        "tenant_004",
    ),
    ("30_app/30_tb_order.sql", "UNIQUE (tenant_id, reference)", "UNIQUE (reference)", "tenant_005"),
]


@pytest.mark.parametrize(("file", "old", "new", "rule"), _EDITS, ids=[e[3] for e in _EDITS])
def test_each_rule_reads_the_example(
    tmp_path: Path, file: str, old: str, new: str, rule: str
) -> None:
    project = tmp_path / "example"
    shutil.copytree(EXAMPLE, project)
    target = project / "db" / "schema" / file
    text = target.read_text()
    assert old in text, f"{file} no longer holds {old!r}; update the edit"
    target.write_text(text.replace(old, new, 1))

    code, payload = _lint(project)

    assert rule in {v["rule_id"] for v in payload["violations"]["items"]}
    assert code != 0


def test_the_family_is_the_one_every_edit_trips() -> None:
    assert tuple(sorted({e[3] for e in _EDITS})) == FAMILY
