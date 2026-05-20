"""Unit tests for TreeRenumber — Phase 4 of issue #111.

No database required.  All tests use pytest's ``tmp_path`` fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.core.tree_renumber import RenumberPlan, RenumberResult, TreeRenumber, _stem_from_path

# ---------------------------------------------------------------------------
# _stem_from_path helper
# ---------------------------------------------------------------------------


class TestStemFromPath:
    def test_strips_decimal_prefix(self) -> None:
        assert _stem_from_path(Path("00042_create_item.sql")) == "create_item"

    def test_strips_short_decimal_prefix(self) -> None:
        assert _stem_from_path(Path("03_init.sql")) == "init"

    def test_strips_hex_prefix(self) -> None:
        assert _stem_from_path(Path("0001a_create.sql")) == "create"

    def test_no_prefix_returns_stem(self) -> None:
        assert _stem_from_path(Path("create_item.sql")) == "create_item"

    def test_works_with_full_path(self) -> None:
        assert _stem_from_path(Path("db/schema/funcs/00001_create.sql")) == "create"

    def test_single_digit_prefix(self) -> None:
        assert _stem_from_path(Path("1_bootstrap.sql")) == "bootstrap"


# ---------------------------------------------------------------------------
# RenumberPlan dataclass
# ---------------------------------------------------------------------------


class TestRenumberPlan:
    def test_fields_accessible(self, tmp_path: Path) -> None:
        p = RenumberPlan(
            old_path=tmp_path / "old.sql",
            new_path=tmp_path / "new.sql",
            old_name="create_item",
            new_name="update_item",
        )
        assert p.old_path == tmp_path / "old.sql"
        assert p.old_name == "create_item"
        assert p.new_name == "update_item"

    def test_same_name_when_no_rename(self, tmp_path: Path) -> None:
        p = RenumberPlan(
            old_path=tmp_path / "old.sql",
            new_path=tmp_path / "new.sql",
            old_name="create_item",
            new_name="create_item",
        )
        assert p.old_name == p.new_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _schema(tmp_path: Path) -> Path:
    s = tmp_path / "schema"
    s.mkdir()
    return s


def _funcs(schema: Path, *sub: str) -> Path:
    d = schema
    for s in sub:
        d = d / s
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Cycle 1: build_plans — single file
# ---------------------------------------------------------------------------


class TestBuildPlansFile:
    """Tests for TreeRenumber.build_plans with file inputs."""

    def test_file_to_file_single_plan(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.touch()
        new = funcs / "00005_create_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)

        assert len(plans) == 1
        assert plans[0].old_path == old.resolve()
        assert plans[0].new_path == new.resolve()

    def test_file_to_file_names_extracted(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.touch()
        new = funcs / "00005_update_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)

        assert plans[0].old_name == "create_item"
        assert plans[0].new_name == "update_item"

    def test_file_to_file_same_name_when_only_prefix_changes(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.touch()
        new = funcs / "00005_create_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)

        assert plans[0].old_name == plans[0].new_name == "create_item"

    def test_file_to_dir_allocates_prefix(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        other = _funcs(schema, "other")
        (other / "00003_existing.sql").touch()
        old = funcs / "00001_create_item.sql"
        old.touch()

        plans = TreeRenumber(schema).build_plans(old, other)

        assert len(plans) == 1
        assert plans[0].new_path.parent == other.resolve()
        # Next after 3 is 4
        assert plans[0].new_path.name.startswith("00004_")

    def test_file_to_dir_preserves_stem(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        other = _funcs(schema, "other")
        old = funcs / "00001_create_item.sql"
        old.touch()

        plans = TreeRenumber(schema).build_plans(old, other)

        assert "create_item" in plans[0].new_path.name

    def test_nonexistent_old_file_raises(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"  # not created
        new = funcs / "00002_create_item.sql"

        with pytest.raises(ValueError, match="does not exist"):
            TreeRenumber(schema).build_plans(old, new)


# ---------------------------------------------------------------------------
# Cycle 1: execute — single-file move (no rename)
# ---------------------------------------------------------------------------


class TestExecuteSingleFile:
    """Tests for TreeRenumber.execute — single file, no name change."""

    def test_old_file_removed(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        new = funcs / "00005_create_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)
        TreeRenumber(schema).execute(plans)

        assert not old.exists()

    def test_new_file_created(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        new = funcs / "00005_create_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)
        TreeRenumber(schema).execute(plans)

        assert new.exists()

    def test_content_preserved(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 42;")
        new = funcs / "00005_create_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)
        TreeRenumber(schema).execute(plans)

        assert new.read_text() == "SELECT 42;"

    def test_dry_run_nothing_moved(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        new = funcs / "00005_create_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)
        TreeRenumber(schema).execute(plans, dry_run=True)

        assert old.exists()
        assert not new.exists()

    def test_result_contains_plans(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        new = funcs / "00005_create_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)
        result = TreeRenumber(schema).execute(plans)

        assert isinstance(result, RenumberResult)
        assert len(result.plans) == 1


# ---------------------------------------------------------------------------
# Cycle 2: cross-reference detection
# ---------------------------------------------------------------------------


class TestFindReferences:
    """Tests for cross-reference detection."""

    def test_finds_reference_in_other_file(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.write_text("CREATE FUNCTION create_item() RETURNS void AS $$ $$ LANGUAGE sql;")
        other = funcs / "00002_wrapper.sql"
        other.write_text("SELECT create_item() FROM items;")
        new = funcs / "00003_create_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)
        result = TreeRenumber(schema).execute(plans, dry_run=True)

        ref_files = [rw.ref_file for rw in result.ref_rewrites]
        assert other.resolve() in ref_files

    def test_no_references_when_none_exist(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        other = funcs / "00002_unrelated.sql"
        other.write_text("SELECT something_else();")
        new = funcs / "00003_create_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)
        result = TreeRenumber(schema).execute(plans, dry_run=True)

        assert result.ref_rewrites == []

    def test_moved_file_not_counted_as_ref(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT create_item();")  # self-reference in content
        new = funcs / "00003_create_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)
        result = TreeRenumber(schema).execute(plans, dry_run=True)

        # The moved file itself should not be in ref_rewrites
        ref_files = [rw.ref_file for rw in result.ref_rewrites]
        assert old.resolve() not in ref_files

    def test_finds_call_style_reference(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_process_order.sql"
        old.write_text("SELECT 1;")
        other = funcs / "00002_trigger.sql"
        other.write_text("CALL process_order(NEW.id);")
        new = funcs / "00003_process_order.sql"

        plans = TreeRenumber(schema).build_plans(old, new)
        result = TreeRenumber(schema).execute(plans, dry_run=True)

        ref_files = [rw.ref_file for rw in result.ref_rewrites]
        assert other.resolve() in ref_files


# ---------------------------------------------------------------------------
# Cycle 3: reference rewriting
# ---------------------------------------------------------------------------


class TestReferenceRewriting:
    """Tests for cross-reference rewriting when function name changes."""

    def test_rewrites_select_reference(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        other = funcs / "00002_wrapper.sql"
        other.write_text("SELECT create_item() FROM items;")
        new = funcs / "00003_update_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)
        TreeRenumber(schema).execute(plans)

        text = other.read_text()
        assert "update_item()" in text
        assert "create_item()" not in text

    def test_no_rewrite_when_name_unchanged(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        other = funcs / "00002_wrapper.sql"
        original = "SELECT create_item() FROM items;"
        other.write_text(original)
        new = funcs / "00005_create_item.sql"  # same verb, different prefix

        plans = TreeRenumber(schema).build_plans(old, new)
        TreeRenumber(schema).execute(plans)

        assert other.read_text() == original

    def test_ref_rewrites_recorded_in_result(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        other = funcs / "00002_wrapper.sql"
        other.write_text("SELECT create_item();")
        new = funcs / "00003_update_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)
        result = TreeRenumber(schema).execute(plans)

        assert len(result.ref_rewrites) == 1
        rw = result.ref_rewrites[0]
        assert rw.old_name == "create_item"
        assert rw.new_name == "update_item"
        assert rw.ref_file == other.resolve()

    def test_dry_run_does_not_rewrite(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        other = funcs / "00002_wrapper.sql"
        original = "SELECT create_item();"
        other.write_text(original)
        new = funcs / "00003_update_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)
        TreeRenumber(schema).execute(plans, dry_run=True)

        assert other.read_text() == original

    def test_dangling_refs_detected_after_rewrite(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        # This file references old name in a string literal — won't be caught
        other = funcs / "00002_dynamic.sql"
        other.write_text("EXECUTE 'SELECT create_item()';")
        new = funcs / "00003_update_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)
        result = TreeRenumber(schema).execute(plans)

        # The literal-string reference remains as a dangling ref
        dangling_names = [name for _, name in result.dangling_refs]
        assert "create_item" in dangling_names

    def test_no_dangling_refs_when_all_rewritten(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        other = funcs / "00002_wrapper.sql"
        other.write_text("SELECT create_item();")
        new = funcs / "00003_update_item.sql"

        plans = TreeRenumber(schema).build_plans(old, new)
        result = TreeRenumber(schema).execute(plans)

        assert result.dangling_refs == []


# ---------------------------------------------------------------------------
# Cycle 4: subtree move
# ---------------------------------------------------------------------------


class TestSubtreeMove:
    """Tests for moving an entire directory subtree."""

    def test_subtree_all_files_moved(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        src = _funcs(schema, "catalog")
        dst = _funcs(schema, "public")
        (src / "00001_create.sql").write_text("SELECT 1;")
        (src / "00002_update.sql").write_text("SELECT 2;")

        plans = TreeRenumber(schema).build_plans(src, dst)
        TreeRenumber(schema).execute(plans)

        assert not any(src.iterdir())
        assert len(list(dst.glob("*.sql"))) == 2

    def test_subtree_sequential_prefixes_in_target(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        src = _funcs(schema, "catalog")
        dst = _funcs(schema, "public")
        (src / "00001_create.sql").write_text("SELECT 1;")
        (src / "00002_update.sql").write_text("SELECT 2;")

        plans = TreeRenumber(schema).build_plans(src, dst)
        TreeRenumber(schema).execute(plans)

        names = sorted(f.name for f in dst.glob("*.sql"))
        assert names[0].startswith("00001_")
        assert names[1].startswith("00002_")

    def test_subtree_preserves_sort_order(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        src = _funcs(schema, "catalog")
        dst = _funcs(schema, "public")
        (src / "00001_alpha.sql").write_text("SELECT 'alpha';")
        (src / "00002_beta.sql").write_text("SELECT 'beta';")

        plans = TreeRenumber(schema).build_plans(src, dst)
        TreeRenumber(schema).execute(plans)

        names = sorted(f.name for f in dst.glob("*.sql"))
        assert "alpha" in names[0]
        assert "beta" in names[1]

    def test_subtree_dry_run_nothing_moved(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        src = _funcs(schema, "catalog")
        dst = _funcs(schema, "public")
        f1 = src / "00001_create.sql"
        f1.write_text("SELECT 1;")

        plans = TreeRenumber(schema).build_plans(src, dst)
        TreeRenumber(schema).execute(plans, dry_run=True)

        assert f1.exists()
        assert not any(dst.iterdir())

    def test_subtree_correct_plan_count(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        src = _funcs(schema, "catalog")
        dst = _funcs(schema, "public")
        (src / "00001_create.sql").touch()
        (src / "00002_update.sql").touch()
        (src / "00003_delete.sql").touch()

        plans = TreeRenumber(schema).build_plans(src, dst)

        assert len(plans) == 3

    def test_subtree_ignores_non_sql_files(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        src = _funcs(schema, "catalog")
        dst = _funcs(schema, "public")
        (src / "00001_create.sql").touch()
        (src / "README.md").touch()

        plans = TreeRenumber(schema).build_plans(src, dst)

        assert len(plans) == 1


# ---------------------------------------------------------------------------
# Cycle 3: refusal modes — collision + cross-repo references
# ---------------------------------------------------------------------------


class TestRenumberRefusesOnCollision:
    """A renumber that would clobber an existing file at the target must refuse."""

    def test_execute_raises_when_target_already_exists(self, tmp_path: Path) -> None:
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create.sql"
        old.write_text("-- old")
        existing_target = funcs / "00005_create.sql"
        existing_target.write_text("-- already here")

        renum = TreeRenumber(schema)
        plans = renum.build_plans(old, existing_target)
        with pytest.raises(ValueError, match="collision|exists|already"):
            renum.execute(plans)

        # Both files still exist; nothing was moved.
        assert old.exists()
        assert existing_target.read_text() == "-- already here"

    def test_build_plans_does_not_raise_on_collision(self, tmp_path: Path) -> None:
        """build_plans is read-only; collision must surface at execute."""
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create.sql"
        old.write_text("-- old")
        existing_target = funcs / "00005_create.sql"
        existing_target.write_text("-- already here")

        renum = TreeRenumber(schema)
        plans = renum.build_plans(old, existing_target)  # must not raise
        assert len(plans) == 1


class TestRenumberCrossRepoReferences:
    """``execute`` must refuse when the old filename appears outside ``db/``.

    Application code or templates that reference SQL filenames literally
    (``Path("db/schema/00001_users.sql").read_text()``) would silently break
    after a renumber.  The plan calls for a ``git grep`` (or fs walk) of the
    whole repo, refusal if any non-``db/`` hit is found, and a ``force=True``
    escape hatch.
    """

    def _make_repo(self, tmp_path: Path) -> tuple[Path, Path]:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "db" / "schema" / "functions").mkdir(parents=True)
        return repo, repo / "db" / "schema"

    def test_execute_refuses_when_old_filename_referenced_outside_db_dir(
        self, tmp_path: Path
    ) -> None:
        repo, schema = self._make_repo(tmp_path)
        old = schema / "functions" / "00001_create_item.sql"
        old.write_text("-- old")
        new = schema / "functions" / "00005_create_item.sql"

        # Application code references the literal filename outside db/.
        (repo / "app").mkdir()
        (repo / "app" / "loader.py").write_text(
            'SQL = Path("db/schema/functions/00001_create_item.sql").read_text()\n'
        )

        renum = TreeRenumber(schema, repo_root=repo)
        plans = renum.build_plans(old, new)
        with pytest.raises(ValueError, match="referenced outside"):
            renum.execute(plans)

        # Nothing moved.
        assert old.exists()
        assert not new.exists()

    def test_execute_proceeds_when_force_set_despite_cross_repo_hit(self, tmp_path: Path) -> None:
        repo, schema = self._make_repo(tmp_path)
        old = schema / "functions" / "00001_create_item.sql"
        old.write_text("-- old")
        new = schema / "functions" / "00005_create_item.sql"
        (repo / "app").mkdir()
        (repo / "app" / "loader.py").write_text(
            'SQL = Path("db/schema/functions/00001_create_item.sql").read_text()\n'
        )

        renum = TreeRenumber(schema, repo_root=repo)
        plans = renum.build_plans(old, new)
        result = renum.execute(plans, force=True)

        # Move went through.
        assert not old.exists()
        assert new.exists()
        # The cross-repo hit is reported on the result for visibility.
        assert any("loader.py" in str(p) for p in result.cross_repo_refs)

    def test_execute_ignores_hits_inside_db_dir(self, tmp_path: Path) -> None:
        """Other SQL files referencing the old name are handled by the regular
        ref-rewrite path — they must not count as cross-repo refusals."""
        repo, schema = self._make_repo(tmp_path)
        old = schema / "functions" / "00001_create_item.sql"
        old.write_text("-- defines create_item")
        new = schema / "functions" / "00005_update_item.sql"
        # A sibling SQL file references the old name — fine.
        (schema / "functions" / "00010_caller.sql").write_text("SELECT create_item();\n")

        renum = TreeRenumber(schema, repo_root=repo)
        plans = renum.build_plans(old, new)
        # Must not raise — sibling SQL ref is handled by ref-rewrite path.
        result = renum.execute(plans)
        assert not old.exists()
        assert new.exists()
        assert result.cross_repo_refs == []

    def test_execute_works_without_repo_root_param(self, tmp_path: Path) -> None:
        """When ``repo_root`` is None, the scan is best-effort and must not crash."""
        schema = _schema(tmp_path)
        funcs = _funcs(schema, "functions")
        old = funcs / "00001_create.sql"
        old.write_text("-- old")
        new = funcs / "00005_create.sql"

        renum = TreeRenumber(schema)  # no repo_root
        plans = renum.build_plans(old, new)
        result = renum.execute(plans)  # must not raise
        assert not old.exists()
        assert new.exists()
        assert isinstance(result.cross_repo_refs, list)
