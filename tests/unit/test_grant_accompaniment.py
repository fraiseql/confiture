"""Unit tests for grant accompaniment validation (Issue #66)."""

from pathlib import Path
from unittest.mock import MagicMock

from confiture.core.grant_accompaniment import GrantAccompanimentChecker
from confiture.models.git import GrantAccompanimentReport


class TestGrantAccompanimentReport:
    """Tests for GrantAccompanimentReport dataclass."""

    def test_no_grant_changes_is_valid(self):
        report = GrantAccompanimentReport(
            has_grant_changes=False,
            has_migration_changes=False,
            grant_files_changed=[],
            migration_files_staged=[],
        )
        assert report.is_valid is True

    def test_grant_change_with_migration_is_valid(self):
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=True,
            grant_files_changed=[Path("db/7_grant/741_grant_reporter.sql")],
            migration_files_staged=[Path("db/migrations/20260301120000_add_reporter.up.sql")],
        )
        assert report.is_valid is True

    def test_grant_change_without_migration_is_invalid(self):
        # Semantic engine: an unmatched (or unverifiable) grant with no
        # migration is the failing case. A grant change carrying *nothing*
        # representable + no migration is the no-op loosening (tested below).
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=False,
            grant_files_changed=[Path("db/7_grant/741_grant_reporter.sql")],
            migration_files_staged=[],
            unmatched_grants=[{"statement": "GRANT SELECT ON s.t TO reporter"}],
        )
        assert report.is_valid is False

    def test_unverifiable_grant_without_migration_is_invalid(self):
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=False,
            grant_files_changed=[Path("db/7_grant/741_grant_reporter.sql")],
            migration_files_staged=[],
            unverifiable_notes=["dynamic SQL — could not statically verify"],
        )
        assert report.is_valid is False

    def test_unverifiable_grant_with_migration_degrades_to_valid(self):
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=True,
            grant_files_changed=[Path("db/7_grant/741_grant_reporter.sql")],
            migration_files_staged=[Path("db/migrations/001_x.up.sql")],
            unverifiable_notes=["dynamic SQL — could not statically verify"],
        )
        assert report.is_valid is True

    def test_noop_grant_edit_without_migration_is_valid(self):
        # Comment-only / reorder edit: nothing representable changed, nothing
        # unverifiable. The semantic gate passes without a migration (loosening).
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=False,
            grant_files_changed=[Path("db/7_grant/741_grant_reporter.sql")],
            migration_files_staged=[],
        )
        assert report.is_valid is True

    def test_only_migration_no_grant_is_valid(self):
        report = GrantAccompanimentReport(
            has_grant_changes=False,
            has_migration_changes=True,
            grant_files_changed=[],
            migration_files_staged=[Path("db/migrations/20260301120000_add_reporter.up.sql")],
        )
        assert report.is_valid is True

    def test_summary_no_changes(self):
        report = GrantAccompanimentReport(
            has_grant_changes=False,
            has_migration_changes=False,
            grant_files_changed=[],
            migration_files_staged=[],
        )
        assert "No grant" in report.summary()

    def test_summary_valid(self):
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=True,
            grant_files_changed=[Path("db/7_grant/741_grant_reporter.sql")],
            migration_files_staged=[Path("db/migrations/20260301120000_add_reporter.up.sql")],
        )
        assert "accompanied" in report.summary()

    def test_summary_invalid(self):
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=False,
            grant_files_changed=[Path("db/7_grant/741_grant_reporter.sql")],
            migration_files_staged=[],
            unmatched_grants=[{"statement": "GRANT SELECT ON s.t TO reporter"}],
        )
        assert "not carried" in report.summary()

    def test_to_dict_structure(self):
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=False,
            grant_files_changed=[Path("db/7_grant/741_grant_reporter.sql")],
            migration_files_staged=[],
            unmatched_grants=[{"statement": "GRANT SELECT ON s.t TO reporter"}],
            unverifiable_notes=["a note"],
        )
        d = report.to_dict()
        assert "is_valid" in d
        assert "has_grant_changes" in d
        assert "has_migration_changes" in d
        assert "grant_files_changed" in d
        assert "migration_files_staged" in d
        assert "unmatched_grants" in d
        assert "unverifiable_notes" in d
        assert d["is_valid"] is False
        assert d["grant_files_changed"] == ["db/7_grant/741_grant_reporter.sql"]


class TestGrantAccompanimentChecker:
    """Tests for GrantAccompanimentChecker."""

    def _make_checker(self):
        checker = GrantAccompanimentChecker()
        checker.git_repo = MagicMock()
        return checker

    def test_no_grant_changes_is_valid(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = []
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True
        assert report.has_grant_changes is False

    def test_grant_change_with_migration_is_valid(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/7_grant/741_grant_reporter.sql"),
            Path("db/migrations/20260301120000_add_reporter.up.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True
        assert report.has_grant_changes is True
        assert report.has_migration_changes is True

    def test_grant_change_without_migration_is_invalid(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/7_grant/741_grant_reporter.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is False
        assert report.has_grant_changes is True
        assert report.has_migration_changes is False

    def test_only_migration_no_grant_is_valid(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/migrations/20260301120000_add_reporter.up.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True
        assert report.has_grant_changes is False

    def test_report_lists_grant_files(self):
        checker = self._make_checker()
        grant_file = Path("db/7_grant/741_grant_reporter.sql")
        checker.git_repo.get_staged_files.return_value = [grant_file]
        report = checker.check_accompaniment(staged_only=True)
        assert grant_file in report.grant_files_changed

    def test_report_lists_migration_files(self):
        checker = self._make_checker()
        migration_file = Path("db/migrations/20260301120000_add_reporter.up.sql")
        checker.git_repo.get_staged_files.return_value = [migration_file]
        report = checker.check_accompaniment(staged_only=True)
        assert migration_file in report.migration_files_staged

    def test_grant_in_wrong_dir_is_ignored(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/other/grant.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.has_grant_changes is False
        assert report.is_valid is True

    def test_non_up_sql_migration_not_counted(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/7_grant/741_grant_reporter.sql"),
            Path("db/migrations/20260301120000_add_reporter.down.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.has_migration_changes is False
        assert report.is_valid is False

    def test_grant_change_with_python_migration_is_valid(self):
        """Issue #162: a Python migration counts as an accompanying migration."""
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/7_grant/741_grant_reporter.sql"),
            Path("db/migrations/20260613130000_add_reporter.py"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True
        assert report.has_migration_changes is True

    def test_python_init_module_not_counted(self):
        """__init__.py is package machinery, not a migration (issue #162)."""
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/7_grant/741_grant_reporter.sql"),
            Path("db/migrations/__init__.py"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.has_migration_changes is False
        assert report.is_valid is False

    def test_private_python_module_not_counted(self):
        """_-prefixed modules are helpers, not migrations (issue #162)."""
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/7_grant/741_grant_reporter.sql"),
            Path("db/migrations/_helpers.py"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.has_migration_changes is False
        assert report.is_valid is False

    def test_nested_grant_file_is_detected(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/7_grant/subdir/grant.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.has_grant_changes is True

    def test_empty_repo_is_valid(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = []
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True

    def test_staged_only_uses_get_staged_files(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = []
        checker.check_accompaniment(staged_only=True)
        checker.git_repo.get_staged_files.assert_called_once()
        checker.git_repo.get_changed_files.assert_not_called()

    def test_ref_mode_uses_get_changed_files(self):
        checker = self._make_checker()
        checker.git_repo.get_changed_files.return_value = []
        checker.check_accompaniment(base_ref="origin/main", target_ref="HEAD", staged_only=False)
        checker.git_repo.get_changed_files.assert_called_once_with("origin/main", "HEAD")
        checker.git_repo.get_staged_files.assert_not_called()

    def test_custom_grant_dir(self):
        checker = GrantAccompanimentChecker(grant_dir="db/grants")
        checker.git_repo = MagicMock()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/grants/reporter.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.has_grant_changes is True

    def test_custom_migrations_dir(self):
        checker = GrantAccompanimentChecker(migrations_dir="db/custom_migrations")
        checker.git_repo = MagicMock()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/7_grant/grant.sql"),
            Path("db/custom_migrations/001_foo.up.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.has_migration_changes is True


class TestSemanticGrantMatching:
    """Content-bearing tests for the semantic engine (issue #162, Phase 3).

    Unlike the MagicMock-only tests above (which exercise the degradation
    path), these stub the git content reads so the engine can actually parse
    and compare GRANT/REVOKE statements.
    """

    GRANT = Path("db/7_grant/71_grant.sql")
    MIG_SQL = Path("db/migrations/20260613130000_x.up.sql")
    MIG_PY = Path("db/migrations/20260613130000_x.py")

    def _checker(
        self,
        staged_files,
        target_contents,
        base_contents=None,
    ):
        checker = GrantAccompanimentChecker()
        git = MagicMock()
        git.get_staged_files.return_value = list(staged_files)
        target = {p.as_posix(): c for p, c in target_contents.items()}
        base = {p.as_posix(): c for p, c in (base_contents or {}).items()}
        git.get_staged_file_content.side_effect = lambda p: target.get(p.as_posix())
        # In staged mode the diff base is HEAD; serve base content from here.
        git.get_file_at_ref.side_effect = lambda p, ref: base.get(p.as_posix())
        git.get_merge_base.return_value = "HEAD"
        checker.git_repo = git
        return checker

    def test_semantic_match_passes(self):
        checker = self._checker(
            [self.GRANT, self.MIG_SQL],
            {
                self.GRANT: "GRANT SELECT ON s.t TO reporter;",
                self.MIG_SQL: "GRANT SELECT ON s.t TO reporter;",
            },
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True
        assert report.unmatched_grants == []

    def test_semantic_mismatch_fails_and_names_grant(self):
        checker = self._checker(
            [self.GRANT, self.MIG_SQL],
            {
                self.GRANT: "GRANT SELECT ON s.t TO reporter;",
                self.MIG_SQL: "GRANT SELECT ON other.tbl TO someone;",
            },
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is False
        assert len(report.unmatched_grants) == 1
        stmt = report.unmatched_grants[0]
        assert stmt["schema"] == "s"
        assert stmt["object"] == "t"
        assert stmt["grantee"] == "reporter"
        assert "GRANT SELECT ON s.t TO reporter" in stmt["statement"]

    def test_diff_aware_only_changed_grant_required(self):
        """Editing one grant in a many-grant file requires only that grant."""
        checker = self._checker(
            [self.GRANT, self.MIG_SQL],
            {
                self.GRANT: "GRANT SELECT ON s.a TO r;\nGRANT SELECT ON s.b TO r;\nGRANT SELECT ON s.c TO r;",
                self.MIG_SQL: "GRANT SELECT ON s.c TO r;",
            },
            base_contents={
                self.GRANT: "GRANT SELECT ON s.a TO r;\nGRANT SELECT ON s.b TO r;",
            },
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True
        assert report.unmatched_grants == []

    def test_grant_all_matches_explicit_privileges(self):
        checker = self._checker(
            [self.GRANT, self.MIG_SQL],
            {
                self.GRANT: "GRANT ALL ON s.t TO r;",
                self.MIG_SQL: (
                    "GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
                    "ON s.t TO r;"
                ),
            },
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True

    def test_revoke_match(self):
        checker = self._checker(
            [self.GRANT, self.MIG_SQL],
            {
                self.GRANT: "REVOKE SELECT ON s.t FROM r;",
                self.MIG_SQL: "REVOKE SELECT ON s.t FROM r;",
            },
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True

    def test_schema_wide_grant_match(self):
        checker = self._checker(
            [self.GRANT, self.MIG_SQL],
            {
                self.GRANT: "GRANT SELECT ON ALL TABLES IN SCHEMA s TO r;",
                self.MIG_SQL: "GRANT SELECT ON ALL TABLES IN SCHEMA s TO r;",
            },
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True

    def test_noop_comment_edit_passes_without_migration(self):
        checker = self._checker(
            [self.GRANT],
            {self.GRANT: "-- a new comment\nGRANT SELECT ON s.t TO r;"},
            base_contents={self.GRANT: "GRANT SELECT ON s.t TO r;"},
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True
        assert report.unmatched_grants == []
        assert report.unverifiable_notes == []

    def test_python_migration_carries_grant(self):
        checker = self._checker(
            [self.GRANT, self.MIG_PY],
            {
                self.GRANT: "GRANT SELECT ON s.t TO reporter;",
                self.MIG_PY: (
                    "from confiture import Migration\n"
                    "class M(Migration):\n"
                    "    def up(self):\n"
                    "        self.execute('GRANT SELECT ON s.t TO reporter;')\n"
                ),
            },
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True
        assert report.unmatched_grants == []

    def test_python_migration_missing_grant_fails(self):
        checker = self._checker(
            [self.GRANT, self.MIG_PY],
            {
                self.GRANT: "GRANT SELECT ON s.t TO reporter;",
                self.MIG_PY: (
                    "from confiture import Migration\n"
                    "class M(Migration):\n"
                    "    def up(self):\n"
                    "        self.execute('CREATE TABLE s.t (id int);')\n"
                ),
            },
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is False
        assert len(report.unmatched_grants) == 1

    # ---- D9 silent-pass set: degrade + note, fail without a migration ----

    def test_unmodeled_database_grant_fails_without_migration(self):
        checker = self._checker(
            [self.GRANT],
            {self.GRANT: "GRANT CONNECT ON DATABASE foo TO r;"},
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is False
        assert any("DATABASE" in n or "unmodeled" in n for n in report.unverifiable_notes)

    def test_unmodeled_database_grant_passes_with_migration(self):
        checker = self._checker(
            [self.GRANT, self.MIG_SQL],
            {
                self.GRANT: "GRANT CONNECT ON DATABASE foo TO r;",
                self.MIG_SQL: "GRANT CONNECT ON DATABASE foo TO r;",
            },
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True
        assert report.unverifiable_notes  # surfaced, even though it passes

    def test_alter_default_privileges_degrades(self):
        checker = self._checker(
            [self.GRANT],
            {self.GRANT: "ALTER DEFAULT PRIVILEGES IN SCHEMA s GRANT SELECT ON TABLES TO r;"},
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is False
        assert any(
            "alter_default_privileges" in n.lower() or "default" in n.lower()
            for n in report.unverifiable_notes
        )

    def test_column_level_grant_degrades(self):
        checker = self._checker(
            [self.GRANT],
            {self.GRANT: "GRANT SELECT (col1) ON s.t TO r;"},
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is False
        assert any("column" in n.lower() for n in report.unverifiable_notes)

    def test_dynamic_sql_grant_degrades(self):
        checker = self._checker(
            [self.GRANT],
            {self.GRANT: "DO $$ BEGIN EXECUTE format('GRANT SELECT ON %I TO r', 't'); END $$;"},
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is False
        assert any("dynamic" in n.lower() for n in report.unverifiable_notes)

    def test_search_path_relative_grant_degrades(self):
        checker = self._checker(
            [self.GRANT],
            {self.GRANT: "SET search_path = myschema;\nGRANT SELECT ON t TO r;"},
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is False
        assert any("search_path" in n for n in report.unverifiable_notes)

    def test_removed_grant_degrades_to_file_presence(self):
        checker = self._checker(
            [self.GRANT],
            {self.GRANT: "-- emptied\n"},
            base_contents={self.GRANT: "GRANT SELECT ON s.t TO r;"},
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is False
        assert any("removed" in n.lower() for n in report.unverifiable_notes)

    def test_grant_option_only_change_degrades(self):
        checker = self._checker(
            [self.GRANT],
            {self.GRANT: "GRANT SELECT ON s.t TO r WITH GRANT OPTION;"},
            base_contents={self.GRANT: "GRANT SELECT ON s.t TO r;"},
        )
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is False
        assert any("GRANT OPTION" in n for n in report.unverifiable_notes)
