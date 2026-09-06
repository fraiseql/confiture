"""``docs/guides/dry-run.md`` shows what ``migrate up --dry-run`` prints (ENG-11).

The example block is rendered from a fixed two-migration fixture; when the
renderer changes, the doc changes with it or this test says so.
"""

from __future__ import annotations

from pathlib import Path

from confiture.cli.dry_run_summary import build_dry_run_summary, render_dry_run_text

GUIDE = Path(__file__).resolve().parents[3] / "docs" / "guides" / "dry-run.md"
FIXTURE = {
    "001_create_initial_schema.up.sql": "CREATE TABLE users (id INT PRIMARY KEY);\n",
    "002_add_user_table.up.sql": (
        "CREATE TABLE user_profiles (user_id INT REFERENCES users (id), bio TEXT);\n"
    ),
}


def _documented_block() -> str:
    text = GUIDE.read_text()
    start = text.index("**Output**:\n```\n") + len("**Output**:\n```\n")
    return text[start : text.index("```", start)]


def test_guide_example_is_the_renderer_output(tmp_path: Path) -> None:
    for name, sql in FIXTURE.items():
        (tmp_path / name).write_text(sql)
        (tmp_path / name.replace(".up.sql", ".down.sql")).write_text("SELECT 1;\n")
    summary = build_dry_run_summary(
        [("001", "create_initial_schema"), ("002", "add_user_table")],
        migrations_dir=tmp_path,
        migration_id="dry_run_local",
        mode="analysis",
    )
    rendered = "Analyzing migrations without execution...\n\n" + render_dry_run_text(summary)

    assert _documented_block() == rendered


def test_guide_shows_no_fabricated_estimates() -> None:
    block = _documented_block()
    for fabricated in ("500ms", "1.0MB", "CPU: 30%"):
        assert fabricated not in block
