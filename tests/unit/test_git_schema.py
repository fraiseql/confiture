"""Tests for git-based schema building and comparison.

Tests schema building from git refs, comparison between refs, and DDL change detection.
"""

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from confiture.core.git_schema import GitSchemaBuilder, GitSchemaDiffer
from confiture.core.schema_change import IndexAdded, IndexDropped, TableAdded
from confiture.core.schema_sources import env_segments
from confiture.exceptions import GitError, SchemaError


class TestGitSchemaBuilder:
    """Tests for GitSchemaBuilder class."""

    def test_build_schema_at_ref(self):
        """Test building schema from specific git ref."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            import subprocess

            # Initialize repo
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            # Create confiture config
            config_dir = repo_path / "db" / "environments"
            config_dir.mkdir(parents=True)
            (config_dir / "local.yaml").write_text(
                "database_url: postgresql://localhost/test\n"
                "include_dirs:\n"
                "  - path: db/schema\n"
                "    recursive: true\n"
            )

            # Create schema directory with files
            schema_dir = repo_path / "db" / "schema"
            schema_dir.mkdir(parents=True)
            (schema_dir / "01_users.sql").write_text("CREATE TABLE users (id INT);")
            (schema_dir / "02_posts.sql").write_text("CREATE TABLE posts (id INT);")

            # Commit
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial schema"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            # Build schema from HEAD
            builder = GitSchemaBuilder("local", repo_path)
            schema = builder.build_schema_at_ref("HEAD")

            assert "CREATE TABLE users" in schema
            assert "CREATE TABLE posts" in schema

    def test_build_schema_at_ref_respects_file_order(self):
        """Test that schema building respects file order."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            import subprocess

            # Initialize repo
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            # Create confiture config
            config_dir = repo_path / "db" / "environments"
            config_dir.mkdir(parents=True)
            (config_dir / "local.yaml").write_text(
                "database_url: postgresql://localhost/test\n"
                "include_dirs:\n"
                "  - path: db/schema\n"
                "    recursive: true\n"
            )

            # Create schema files in specific order
            schema_dir = repo_path / "db" / "schema"
            schema_dir.mkdir(parents=True)
            (schema_dir / "01_base.sql").write_text("-- Base\nCREATE TABLE base (id INT);")
            (schema_dir / "02_derived.sql").write_text(
                "-- Derived\nCREATE TABLE derived (base_id INT);"
            )

            # Commit
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial"], cwd=repo_path, check=True, capture_output=True
            )

            # Build and verify order
            builder = GitSchemaBuilder("local", repo_path)
            schema = builder.build_schema_at_ref("HEAD")

            # Find positions of tables
            base_pos = schema.find("CREATE TABLE base")
            derived_pos = schema.find("CREATE TABLE derived")

            assert base_pos < derived_pos, "Files should be ordered: 01_base before 02_derived"

    def test_build_schema_at_ref_empty_returns_empty_string(self):
        """Test that empty schema directory returns empty string."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            import subprocess

            # Initialize repo
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            # Create confiture config with empty schema dir
            config_dir = repo_path / "db" / "environments"
            config_dir.mkdir(parents=True)
            (config_dir / "local.yaml").write_text(
                "database_url: postgresql://localhost/test\n"
                "include_dirs:\n"
                "  - path: db/schema\n"
                "    recursive: true\n"
            )

            schema_dir = repo_path / "db" / "schema"
            schema_dir.mkdir(parents=True)

            # Create initial commit
            (repo_path / "README.md").write_text("# Test")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial"], cwd=repo_path, check=True, capture_output=True
            )

            # Build schema
            builder = GitSchemaBuilder("local", repo_path)
            schema = builder.build_schema_at_ref("HEAD")

            # Should be empty or just whitespace
            assert schema.strip() == ""


class TestGitSchemaDiffer:
    """Tests for GitSchemaDiffer class."""

    def test_compare_refs_detects_new_table(self):
        """Test detecting new table between refs."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            import subprocess

            # Initialize repo
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            # Create confiture config
            config_dir = repo_path / "db" / "environments"
            config_dir.mkdir(parents=True)
            (config_dir / "local.yaml").write_text(
                "database_url: postgresql://localhost/test\n"
                "include_dirs:\n"
                "  - path: db/schema\n"
                "    recursive: true\n"
            )

            # First commit: users table
            schema_dir = repo_path / "db" / "schema"
            schema_dir.mkdir(parents=True)
            (schema_dir / "01_users.sql").write_text("CREATE TABLE users (id INT);")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial"], cwd=repo_path, check=True, capture_output=True
            )

            # Second commit: add posts table
            (schema_dir / "02_posts.sql").write_text("CREATE TABLE posts (id INT);")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Add posts"], cwd=repo_path, check=True, capture_output=True
            )

            # Compare refs
            differ = GitSchemaDiffer("local", repo_path)
            diff = differ.compare_refs("HEAD~1", "HEAD")

            assert diff.has_changes()
            assert sum(isinstance(c, TableAdded) for c in diff.changes) >= 1

    def test_has_ddl_changes_ignores_whitespace(self):
        """Test that whitespace changes are not considered DDL changes."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            import subprocess

            # Initialize repo
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            # Create confiture config
            config_dir = repo_path / "db" / "environments"
            config_dir.mkdir(parents=True)
            (config_dir / "local.yaml").write_text(
                "database_url: postgresql://localhost/test\n"
                "include_dirs:\n"
                "  - path: db/schema\n"
                "    recursive: true\n"
            )

            # Initial commit
            schema_dir = repo_path / "db" / "schema"
            schema_dir.mkdir(parents=True)
            (schema_dir / "users.sql").write_text("CREATE TABLE users (id INT);")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial"], cwd=repo_path, check=True, capture_output=True
            )

            # Change only whitespace
            (schema_dir / "users.sql").write_text("CREATE TABLE users (  id INT  );")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Whitespace"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            # Compare refs
            differ = GitSchemaDiffer("local", repo_path)
            diff = differ.compare_refs("HEAD~1", "HEAD")
            has_ddl_changes = differ.has_ddl_changes(diff)

            # Should have no meaningful DDL changes (only whitespace)
            assert not has_ddl_changes

    def test_has_ddl_changes_detects_real_ddl(self):
        """Test that real DDL changes are detected."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            import subprocess

            # Initialize repo
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            # Create confiture config
            config_dir = repo_path / "db" / "environments"
            config_dir.mkdir(parents=True)
            (config_dir / "local.yaml").write_text(
                "database_url: postgresql://localhost/test\n"
                "include_dirs:\n"
                "  - path: db/schema\n"
                "    recursive: true\n"
            )

            # Initial commit
            schema_dir = repo_path / "db" / "schema"
            schema_dir.mkdir(parents=True)
            (schema_dir / "users.sql").write_text("CREATE TABLE users (id INT);")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial"], cwd=repo_path, check=True, capture_output=True
            )

            # Add real DDL change (new column)
            (schema_dir / "users.sql").write_text("CREATE TABLE users (id INT, email TEXT);")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Add email column"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            # Compare refs
            differ = GitSchemaDiffer("local", repo_path)
            diff = differ.compare_refs("HEAD~1", "HEAD")
            has_ddl_changes = differ.has_ddl_changes(diff)

            assert has_ddl_changes


# ---------------------------------------------------------------------------
# A ref is compared as the build reads it (#686)
# ---------------------------------------------------------------------------

_HEX_ENV = (
    'database_url: "postgresql://localhost/test"\n'
    "include_dirs:\n  - db/schema\nbuild:\n  sort_mode: hex\n"
)
_TABLE = "CREATE TABLE post (id int, slug text);\n"
_INDEXES = "CREATE INDEX ix_post_id ON post (id);\nCREATE INDEX ix_post_slug ON post (slug);\n"


def _repo(tmp_path: Path, env: str = _HEX_ENV) -> Path:
    root = tmp_path / "repo"
    (root / "db" / "environments").mkdir(parents=True)
    (root / "db" / "environments" / "local.yaml").write_text(env)
    for argv in (
        ["init", "-q"],
        ["config", "user.email", "t@t.com"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", *argv], cwd=root, check=True, capture_output=True)
    return root


def _commit(root: Path, files: dict[str, str | None]) -> None:
    for name, sql in files.items():
        path = root / name
        if sql is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sql)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "c"], cwd=root, check=True, capture_output=True)


def test_compare_refs_reads_hex_order_like_the_build(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _commit(root, {"db/schema/9_tb_post.sql": _TABLE})
    _commit(root, {"db/schema/10_ix_post.sql": "CREATE INDEX ix_post_id ON post (id);\n"})

    diff = GitSchemaDiffer("local", root).compare_refs("HEAD~1", "HEAD")

    assert [type(change) for change in diff.changes] == [IndexAdded]
    assert diff.warnings == []


def test_compare_refs_reports_drops_the_build_orders_correctly(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _commit(root, {"db/schema/9_tb_post.sql": _TABLE, "db/schema/10_ix_post.sql": _INDEXES})
    _commit(root, {"db/schema/10_ix_post.sql": None})

    diff = GitSchemaDiffer("local", root).compare_refs("HEAD~1", "HEAD")

    assert [type(change) for change in diff.changes] == [IndexDropped, IndexDropped]
    assert [warning.code for warning in diff.warnings] == []


def test_compare_refs_names_the_file_pglast_rejects(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _commit(root, {"db/schema/10_tb_post.sql": _TABLE})
    _commit(root, {"db/schema/20_bad.sql": "CREATE TABLE (;\n"})

    with pytest.raises(SchemaError) as caught:
        GitSchemaDiffer("local", root).compare_refs("HEAD~1", "HEAD")

    working = {segment.label: segment.file for segment in env_segments("local", root)}
    assert caught.value.error_code == "DIFFER_400"
    assert caught.value.context["file"] == str(root.resolve() / "db/schema/20_bad.sql")
    assert caught.value.context["file"] == str(working["db/schema/20_bad.sql"])


def test_untracked_include_dirs_are_refused(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _commit(root, {"README": "one\n"})
    _commit(root, {"README": "two\n"})
    (root / "db" / "schema").mkdir()
    (root / "db" / "schema" / "a.sql").write_text(_TABLE)

    with pytest.raises(GitError, match="not tracked") as caught:
        GitSchemaDiffer("local", root).compare_refs("HEAD~1", "HEAD")

    assert caught.value.error_code == "GIT_001"


def test_equal_trees_read_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    _commit(root, {"db/schema/9_tb_post.sql": _TABLE})
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "e"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    differ = GitSchemaDiffer("local", root)
    calls: list[list[str]] = []
    real_run, real_popen = subprocess.run, subprocess.Popen

    def run(argv: list[str], **kwargs: Any) -> Any:
        calls.append(list(argv))
        return real_run(argv, **kwargs)

    def popen(argv: list[str], **kwargs: Any) -> Any:
        calls.append(list(argv))
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", popen)

    assert not differ.compare_refs("HEAD~1", "HEAD").has_changes()
    assert not [argv for argv in calls if {"ls-tree", "cat-file", "show"} & set(argv)]
