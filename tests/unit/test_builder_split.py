"""Unit tests for SchemaBuilder.build_split() (Issue #100)."""

from confiture.core.builder import SchemaBuilder


class TestBuildSplitPartitioning:
    """Test file partitioning between superuser and app buckets."""

    def _setup_project(self, tmp_path, *, superuser_dirs_yaml=""):
        """Create a project with security (superuser) and table (app) dirs."""
        schema_dir = tmp_path / "db" / "schema"
        security_dir = schema_dir / "00_common" / "000_security"
        tables_dir = schema_dir / "10_tables"
        security_dir.mkdir(parents=True)
        tables_dir.mkdir(parents=True)

        (security_dir / "roles.sql").write_text("CREATE ROLE app_role;\n")
        (security_dir / "extensions.sql").write_text("CREATE EXTENSION pgcrypto;\n")
        (tables_dir / "users.sql").write_text("CREATE TABLE users (id serial);\n")
        (tables_dir / "posts.sql").write_text("CREATE TABLE posts (id serial);\n")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        (config_dir / "test.yaml").write_text(f"""
name: test
database_url: postgresql://localhost/test
include_dirs:
  - {schema_dir}
{superuser_dirs_yaml}
""")
        return schema_dir

    def test_no_superuser_dirs_puts_all_in_app(self, tmp_path):
        """With no superuser_dirs, all files go to app output."""
        self._setup_project(tmp_path)
        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        result = builder.build_split(output_dir=tmp_path / "out")

        assert result.success is True
        assert result.superuser_files == 0
        assert result.app_files == 4
        assert result.superuser_size_bytes == 0

    def test_superuser_dirs_splits_files(self, tmp_path):
        """Files under superuser_dirs go to superuser output."""
        self._setup_project(
            tmp_path,
            superuser_dirs_yaml=f"superuser_dirs:\n  - {tmp_path / 'db/schema/00_common/000_security'}",
        )
        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        result = builder.build_split(output_dir=tmp_path / "out")

        assert result.success is True
        assert result.superuser_files == 2  # roles.sql, extensions.sql
        assert result.app_files == 2  # users.sql, posts.sql

    def test_superuser_sql_contains_correct_content(self, tmp_path):
        """Superuser output contains only superuser file content."""
        self._setup_project(
            tmp_path,
            superuser_dirs_yaml=f"superuser_dirs:\n  - {tmp_path / 'db/schema/00_common/000_security'}",
        )
        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        result = builder.build_split(output_dir=tmp_path / "out")

        from pathlib import Path

        superuser_sql = Path(result.superuser_path).read_text()
        app_sql = Path(result.app_path).read_text()

        assert "CREATE ROLE" in superuser_sql
        assert "CREATE EXTENSION" in superuser_sql
        assert "CREATE TABLE" not in superuser_sql

        assert "CREATE TABLE" in app_sql
        assert "CREATE ROLE" not in app_sql

    def test_app_sql_contains_all_when_no_superuser_dirs(self, tmp_path):
        """Without superuser_dirs, app output contains everything."""
        self._setup_project(tmp_path)
        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        result = builder.build_split(output_dir=tmp_path / "out")

        from pathlib import Path

        app_sql = Path(result.app_path).read_text()
        assert "CREATE ROLE" in app_sql
        assert "CREATE TABLE" in app_sql


class TestBuildSplitOutputFiles:
    """Test output file naming and paths."""

    def test_output_file_names(self, tmp_path):
        """Output files follow schema_{env}_{type}.sql naming."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "table.sql").write_text("CREATE TABLE t (id int);\n")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        (config_dir / "dev.yaml").write_text(f"""
name: dev
database_url: postgresql://localhost/test
include_dirs:
  - {schema_dir}
""")

        builder = SchemaBuilder(env="dev", project_dir=tmp_path)
        result = builder.build_split(output_dir=tmp_path / "out")

        assert result.superuser_path.endswith("schema_dev_superuser.sql")
        assert result.app_path.endswith("schema_dev_app.sql")

    def test_output_dir_created_if_missing(self, tmp_path):
        """build_split creates the output directory if it doesn't exist."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "table.sql").write_text("CREATE TABLE t (id int);\n")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        (config_dir / "test.yaml").write_text(f"""
name: test
database_url: postgresql://localhost/test
include_dirs:
  - {schema_dir}
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        out_dir = tmp_path / "nested" / "output"
        result = builder.build_split(output_dir=out_dir)

        assert out_dir.exists()
        assert result.success is True


class TestBuildSplitBackwardCompatibility:
    """Ensure build_split doesn't affect build()."""

    def test_compute_hash_stable_with_superuser_dirs(self, tmp_path):
        """compute_hash() must not change when superuser_dirs is added (issue #103).

        superuser_dirs is a deployment-time concern that partitions the same
        set of files — it does not change what SQL gets executed, only which
        connection applies it.
        """
        schema_dir = tmp_path / "db" / "schema"
        security_dir = schema_dir / "00_common" / "000_security"
        tables_dir = schema_dir / "10_tables"
        security_dir.mkdir(parents=True)
        tables_dir.mkdir(parents=True)

        (security_dir / "roles.sql").write_text("CREATE ROLE app_role;\n")
        (security_dir / "extensions.sql").write_text("CREATE EXTENSION pgcrypto;\n")
        (tables_dir / "users.sql").write_text("CREATE TABLE users (id serial);\n")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)

        # Config WITHOUT superuser_dirs
        (config_dir / "without.yaml").write_text(f"""
name: without
database_url: postgresql://localhost/test
include_dirs:
  - {schema_dir}
""")

        # Config WITH superuser_dirs (same include_dirs, same SQL files)
        (config_dir / "with_su.yaml").write_text(f"""
name: with_su
database_url: postgresql://localhost/test
include_dirs:
  - {schema_dir}
superuser_dirs:
  - {security_dir}
""")

        builder_without = SchemaBuilder(env="without", project_dir=tmp_path)
        builder_with_su = SchemaBuilder(env="with_su", project_dir=tmp_path)

        assert builder_without.compute_hash() == builder_with_su.compute_hash()

    def test_build_still_produces_single_file(self, tmp_path):
        """build() is unaffected by superuser_dirs config."""
        schema_dir = tmp_path / "db" / "schema"
        security_dir = schema_dir / "00_common" / "000_security"
        security_dir.mkdir(parents=True)
        (security_dir / "roles.sql").write_text("CREATE ROLE app_role;\n")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        (config_dir / "test.yaml").write_text(f"""
name: test
database_url: postgresql://localhost/test
include_dirs:
  - {schema_dir}
superuser_dirs:
  - {security_dir}
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        schema = builder.build()

        # build() still includes everything in one output
        assert "CREATE ROLE" in schema


class TestBuildSplitWithSeeds:
    """Test schema_only filtering with build_split."""

    def test_schema_only_excludes_seeds(self, tmp_path):
        """schema_only=True excludes seed files from both outputs."""
        schema_dir = tmp_path / "db" / "schema"
        tables_dir = schema_dir / "10_tables"
        seeds_dir = tmp_path / "db" / "seeds"
        tables_dir.mkdir(parents=True)
        seeds_dir.mkdir(parents=True)

        (tables_dir / "users.sql").write_text("CREATE TABLE users (id serial);\n")
        (seeds_dir / "dev_data.sql").write_text("INSERT INTO users VALUES (1);\n")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        (config_dir / "test.yaml").write_text(f"""
name: test
database_url: postgresql://localhost/test
include_dirs:
  - {schema_dir}
  - {seeds_dir}
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)

        result_all = builder.build_split(output_dir=tmp_path / "out_all")
        result_schema = builder.build_split(output_dir=tmp_path / "out_schema", schema_only=True)

        assert result_all.app_files == 2  # table + seed
        assert result_schema.app_files == 1  # table only
