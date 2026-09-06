"""The testing frameworks against a real database and a real ``Migrator``.

``confiture.testing.frameworks`` has thorough unit coverage on mocked
connections. These are the two live paths that coverage cannot reach: the
performance profiler timing a genuine ``Migrator.apply()``, and the mutation
runner executing a mutated migration on the server and reporting on it.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from confiture.core.migrator import Migrator
from confiture.models.migration import Migration
from confiture.testing.frameworks.mutation import MutationCategory, MutationRunner
from confiture.testing.frameworks.performance import MigrationPerformanceProfiler


class _CreateWidgets(Migration):
    version = "20260906000001"
    name = "create_widgets"

    def up(self) -> None:
        self.execute("CREATE TABLE widgets (id INT PRIMARY KEY, label TEXT NOT NULL)")
        self.execute("INSERT INTO widgets VALUES (1, 'a'), (2, 'b')")

    def down(self) -> None:
        self.execute("DROP TABLE widgets")


def test_profiler_times_a_real_migrator_apply(clean_test_db: psycopg.Connection) -> None:
    migrator = Migrator(connection=clean_test_db)
    migrator.initialize()
    profiler = MigrationPerformanceProfiler(clean_test_db)

    def run(prof: MigrationPerformanceProfiler) -> None:
        with prof.track_section("apply"):
            migrator.apply(_CreateWidgets(connection=clean_test_db))

    profile = profiler.profile_migration("create_widgets", run)

    assert profile.migration_name == "create_widgets"
    assert profile.total_duration_seconds > 0
    assert list(profile.operations) == ["apply"]
    assert migrator._is_applied("20260906000001")
    count = clean_test_db.execute("SELECT count(*) FROM widgets").fetchone()
    assert count == (2,)


def test_mutation_runner_executes_a_mutated_migration_and_reports(
    clean_test_db: psycopg.Connection, tmp_path: Path
) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_widgets.sql").write_text(
        "CREATE TABLE widgets (id INT PRIMARY KEY, label TEXT NOT NULL);\n"
    )
    runner = MutationRunner(clean_test_db, migrations)

    applicable = [
        m
        for m in runner.registry.get_by_category(MutationCategory.SCHEMA)
        if m.apply("CREATE TABLE widgets (id INT PRIMARY KEY, label TEXT NOT NULL);")
        != "CREATE TABLE widgets (id INT PRIMARY KEY, label TEXT NOT NULL);"
    ]
    assert applicable, "the registry ships no schema mutation that applies to a plain CREATE TABLE"
    mutation = applicable[0]

    result = runner.run_migration_with_mutation("001_widgets", mutation)

    assert result.mutation_applied is True
    assert result.success is True, result.stderr
    relation = clean_test_db.execute("SELECT to_regclass('widgets')").fetchone()
    assert relation is not None

    runner.record_test_result(
        mutation.id, mutation.name, "test_widgets_shape", caught=True, duration=0.01
    )
    report = runner.generate_report()
    # The report is over the whole registry: a mutation nobody tested for has,
    # by definition, survived. One recorded kill out of every default mutation.
    registered = len(runner.registry.list_all())
    assert report.metrics.total_mutations == registered
    assert report.metrics.killed_mutations == 1
    assert report.metrics.survived_mutations == registered - 1
    assert report.metrics.kill_rate == pytest.approx(100.0 / registered)


def test_mutation_runner_reports_a_missing_migration(
    clean_test_db: psycopg.Connection, tmp_path: Path
) -> None:
    runner = MutationRunner(clean_test_db, tmp_path)
    mutation = runner.registry.list_all()[0]

    result = runner.run_migration_with_mutation("does_not_exist", mutation)

    assert result.success is False
    assert result.mutation_applied is False
    assert "not found" in result.stderr
