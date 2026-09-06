"""The JSON sample in ``docs/guides/dry-run.md`` has the shape ``--dry-run --format json`` emits.

The sample is compared key-for-key (top level, per migration, summary) with a payload
built by the real builder for a one-migration project, so a renamed or invented key in
either place fails here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from confiture.cli.dry_run_summary import build_dry_run_summary

REPO_ROOT = Path(__file__).resolve().parents[3]
GUIDE = REPO_ROOT / "docs" / "guides" / "dry-run.md"


def _documented_sample() -> dict:
    text = GUIDE.read_text(encoding="utf-8")
    section = text[text.index("### JSON for CI/CD") :]
    match = re.search(r"```json\n(.*?)```", section, flags=re.S)
    assert match, "dry-run.md has no ```json block under '### JSON for CI/CD'"
    return json.loads(match.group(1))


def _real_payload(tmp_path: Path) -> dict:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_create_initial_schema.up.sql").write_text(
        "CREATE TABLE users (id SERIAL PRIMARY KEY, email TEXT NOT NULL);\n"
    )
    return build_dry_run_summary(
        [("001", "create_initial_schema")],
        migrations_dir=migrations,
        migration_id="dry_run_local",
        mode="analysis",
    )


def test_guide_json_sample_has_the_real_payload_keys(tmp_path: Path) -> None:
    documented = _documented_sample()
    real = _real_payload(tmp_path)
    assert set(documented) == set(real), (
        f"top-level keys: doc has {sorted(set(documented) - set(real))} extra, "
        f"misses {sorted(set(real) - set(documented))}"
    )
    assert set(documented["summary"]) == set(real["summary"])
    assert documented["migrations"], "sample lists no migration"
    assert set(documented["migrations"][0]) == set(real["migrations"][0]), (
        f"per-migration keys: doc has "
        f"{sorted(set(documented['migrations'][0]) - set(real['migrations'][0]))} extra, "
        f"misses {sorted(set(real['migrations'][0]) - set(documented['migrations'][0]))}"
    )


def test_guide_json_sample_is_the_real_payload_for_the_sample_project(
    tmp_path: Path,
) -> None:
    """Not just the keys: the documented values are what the builder returns."""
    assert _documented_sample() == _real_payload(tmp_path)
