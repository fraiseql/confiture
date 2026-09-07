"""``resolve_sql_file`` — the one answer to "which file does this path name?".

Three sites used to answer independently (runtime ``execute_file``, the
idempotency extractor, the import checker's IMP010) and disagreed: a
migration's ``execute_file("db/schema/fn.sql")`` was found from the project
root and reported as escaping the root from any other cwd. Every scenario
below is one the three consumers must now agree on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.core.sql_path import find_project_root, resolve_sql_file


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "db" / "schema").mkdir(parents=True)
    (root / "db" / "migrations").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='x'\n")
    (root / "db" / "schema" / "fn.sql").write_text("SELECT 'project';")
    (root / "db" / "migrations" / "20260101000000_x.py").write_text("")
    return root


@pytest.fixture
def migration(project: Path) -> Path:
    return project / "db" / "migrations" / "20260101000000_x.py"


@pytest.fixture
def elsewhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)
    return other


class TestOrder:
    def test_project_root_is_tried_first(self, project, migration, elsewhere) -> None:
        r = resolve_sql_file(
            "db/schema/fn.sql", migration_file=migration, project_root=project, confine=True
        )

        assert r.outcome == "found"
        assert r.path == (project / "db" / "schema" / "fn.sql").resolve()

    def test_root_wins_when_cwd_holds_a_file_of_the_same_name(
        self, project, migration, elsewhere
    ) -> None:
        (elsewhere / "db" / "schema").mkdir(parents=True)
        (elsewhere / "db" / "schema" / "fn.sql").write_text("SELECT 'cwd';")

        r = resolve_sql_file(
            "db/schema/fn.sql", migration_file=migration, project_root=project, confine=False
        )

        assert r.path is not None
        assert r.path.read_text() == "SELECT 'project';"

    def test_migration_directory_is_tried_second(self, project, migration, elsewhere) -> None:
        (migration.parent / "sql").mkdir()
        (migration.parent / "sql" / "local.sql").write_text("SELECT 'next to migration';")

        r = resolve_sql_file(
            "sql/local.sql", migration_file=migration, project_root=project, confine=True
        )

        assert r.outcome == "found"
        assert r.path == (migration.parent / "sql" / "local.sql").resolve()

    def test_cwd_is_the_last_resort(self, project, migration, elsewhere) -> None:
        (elsewhere / "only_here.sql").write_text("SELECT 'cwd';")

        r = resolve_sql_file(
            "only_here.sql", migration_file=migration, project_root=project, confine=False
        )

        assert r.outcome == "found"
        assert r.path == (elsewhere / "only_here.sql").resolve()

    def test_candidates_are_deduplicated_when_cwd_is_the_root(
        self, project, migration, monkeypatch
    ) -> None:
        monkeypatch.chdir(project)

        r = resolve_sql_file(
            "nope.sql", migration_file=migration, project_root=project, confine=True
        )

        assert r.outcome == "missing"
        assert r.tried == (
            project / "nope.sql",
            migration.parent / "nope.sql",
        )

    def test_monorepo_service_root_beats_a_top_level_db_directory(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """cwd-first picked the wrong file here and then reported it as an escape."""
        mono = tmp_path / "mono"
        (mono / "db" / "schema").mkdir(parents=True)
        (mono / "db" / "schema" / "fn.sql").write_text("SELECT 'wrong service';")
        service = mono / "services" / "a"
        (service / "db" / "schema").mkdir(parents=True)
        (service / "db" / "migrations").mkdir(parents=True)
        (service / "pyproject.toml").write_text("")
        (service / "db" / "schema" / "fn.sql").write_text("SELECT 'right service';")
        migration = service / "db" / "migrations" / "20260101000000_x.py"
        migration.write_text("")
        monkeypatch.chdir(mono)

        r = resolve_sql_file(
            "db/schema/fn.sql",
            migration_file=migration,
            project_root=find_project_root(migration),
            confine=True,
        )

        assert r.outcome == "found"
        assert r.path is not None
        assert r.path.read_text() == "SELECT 'right service';"


class TestAbsolute:
    def test_absolute_path_is_taken_as_is(self, project, migration, elsewhere) -> None:
        target = project / "db" / "schema" / "fn.sql"

        r = resolve_sql_file(target, migration_file=migration, project_root=project, confine=True)

        assert r.outcome == "found"
        assert r.tried == (target,)

    def test_absolute_path_outside_the_root_is_escaped_when_confined(
        self, project, migration, elsewhere
    ) -> None:
        secret = elsewhere / "secret.sql"
        secret.write_text("SECRET")

        r = resolve_sql_file(secret, migration_file=migration, project_root=project, confine=True)

        assert r.outcome == "escaped"
        assert r.path is None

    def test_absolute_path_outside_the_root_is_found_when_unconfined(
        self, project, migration, elsewhere
    ) -> None:
        secret = elsewhere / "secret.sql"
        secret.write_text("SECRET")

        r = resolve_sql_file(secret, migration_file=migration, project_root=project, confine=False)

        assert r.outcome == "found"


class TestConfinement:
    """The v0.8.4 hardening is unchanged: resolve, then test the boundary."""

    def test_traversal_is_escaped(self, project, migration, tmp_path, monkeypatch) -> None:
        (tmp_path / "outside").mkdir()
        (tmp_path / "outside" / "secret.sql").write_text("SECRET")
        monkeypatch.chdir(project)

        r = resolve_sql_file(
            "../outside/secret.sql", migration_file=migration, project_root=project, confine=True
        )

        assert r.outcome == "escaped"
        assert r.path is None

    def test_symlink_inside_pointing_outside_is_escaped(
        self, project, migration, tmp_path, monkeypatch
    ) -> None:
        (tmp_path / "outside").mkdir()
        (tmp_path / "outside" / "secret.sql").write_text("SECRET")
        (project / "db" / "schema" / "link.sql").symlink_to(tmp_path / "outside" / "secret.sql")
        monkeypatch.chdir(project)

        r = resolve_sql_file(
            "db/schema/link.sql", migration_file=migration, project_root=project, confine=True
        )

        assert r.outcome == "escaped"

    def test_escaped_only_when_no_candidate_lies_inside(
        self, project, migration, elsewhere
    ) -> None:
        """An out-of-root cwd hit must not shadow an in-root candidate."""
        (elsewhere / "db" / "schema").mkdir(parents=True)
        (elsewhere / "db" / "schema" / "fn.sql").write_text("SELECT 'cwd';")

        r = resolve_sql_file(
            "db/schema/fn.sql", migration_file=migration, project_root=project, confine=True
        )

        assert r.outcome == "found"
        assert r.path == (project / "db" / "schema" / "fn.sql").resolve()

    def test_confinement_needs_a_root(self, migration) -> None:
        with pytest.raises(ValueError, match="project_root"):
            resolve_sql_file("x.sql", migration_file=migration, project_root=None, confine=True)


class TestMissing:
    def test_missing_names_every_base_tried_in_order(self, project, migration, elsewhere) -> None:
        r = resolve_sql_file(
            "db/schema/nope.sql", migration_file=migration, project_root=project, confine=True
        )

        assert r.outcome == "missing"
        assert r.path is None
        assert r.tried == (
            project / "db/schema/nope.sql",
            migration.parent / "db/schema/nope.sql",
            elsewhere / "db/schema/nope.sql",
        )

    def test_a_directory_is_not_a_file(self, project, migration, elsewhere) -> None:
        r = resolve_sql_file(
            "db/schema", migration_file=migration, project_root=project, confine=True
        )

        assert r.outcome == "missing"

    def test_no_migration_file_and_no_root_means_cwd_only(self, elsewhere) -> None:
        (elsewhere / "here.sql").write_text("SELECT 1;")

        r = resolve_sql_file("here.sql", migration_file=None, project_root=None, confine=False)

        assert r.outcome == "found"
        assert r.tried == (elsewhere / "here.sql",)


class TestFindProjectRoot:
    @pytest.mark.parametrize("anchor", ["pyproject.toml", ".git", "db"])
    def test_nearest_ancestor_with_an_anchor(self, tmp_path: Path, anchor: str) -> None:
        root = tmp_path / "proj"
        (root / "sub" / "deep").mkdir(parents=True)
        (root / anchor).mkdir() if anchor in (".git", "db") else (root / anchor).write_text("")
        migration = root / "sub" / "deep" / "20260101000000_x.py"
        migration.write_text("")

        assert find_project_root(migration) == root.resolve()

    def test_starts_from_the_directory_of_a_file_and_falls_back_to_it(self, tmp_path: Path) -> None:
        lonely = tmp_path / "lonely" / "20260101000000_x.py"
        lonely.parent.mkdir()
        lonely.write_text("")
        # tmp_path itself carries no anchor; nor do its ancestors under pytest's
        # basetemp — but a developer's $TMPDIR might. Accept either the fallback
        # or an ancestor anchor, and pin only that a file resolves from its
        # parent, never from itself.
        root = find_project_root(lonely)

        assert root.is_dir()
        assert lonely.parent.resolve().is_relative_to(root)

    def test_a_directory_resolves_from_itself(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        (root / "db").mkdir(parents=True)

        assert find_project_root(root / "db") == root.resolve()

    def test_cwd_does_not_matter(self, tmp_path: Path, monkeypatch) -> None:
        root = tmp_path / "proj"
        (root / "db" / "migrations").mkdir(parents=True)
        (root / ".git").mkdir()
        monkeypatch.chdir(tmp_path)

        assert find_project_root(root / "db" / "migrations" / "x.py") == root.resolve()
        assert Path(Path.cwd()) == tmp_path
