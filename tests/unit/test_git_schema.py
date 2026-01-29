"""Tests for git-based schema building and comparison.

Tests schema building from git refs, comparison between refs, and DDL change detection.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from confiture.core.git_schema import GitSchemaBuilder, GitSchemaDiffer


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
            assert diff.count_by_type("ADD_TABLE") >= 1

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
