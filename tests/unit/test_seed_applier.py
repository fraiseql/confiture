"""Tests for SeedApplier file discovery.

Phase 9, Cycle 2: File discovery tests
"""

from pathlib import Path

from confiture.core.seed_applier import SeedApplier


def test_find_seed_files_basic(tmp_path):
    """Test seed file discovery with basic seed files."""
    # Create seed directory and files
    seeds_dir = tmp_path / "db" / "seeds"
    seeds_dir.mkdir(parents=True)
    (seeds_dir / "01_users.sql").write_text("INSERT INTO users VALUES (1)")
    (seeds_dir / "02_posts.sql").write_text("INSERT INTO posts VALUES (1)")

    # Create applier and find files
    applier = SeedApplier(seeds_dir=seeds_dir)
    files = applier.find_seed_files()

    # Verify files found and sorted
    assert len(files) == 2
    assert files[0].name == "01_users.sql"
    assert files[1].name == "02_posts.sql"


def test_find_seed_files_sorted_order(tmp_path):
    """Test seed files are returned in sorted order."""
    seeds_dir = tmp_path / "db" / "seeds"
    seeds_dir.mkdir(parents=True)

    # Create files in non-alphabetical order
    (seeds_dir / "03_comments.sql").write_text("INSERT INTO comments...")
    (seeds_dir / "01_users.sql").write_text("INSERT INTO users...")
    (seeds_dir / "02_posts.sql").write_text("INSERT INTO posts...")

    applier = SeedApplier(seeds_dir=seeds_dir)
    files = applier.find_seed_files()

    # Verify sorted order
    names = [f.name for f in files]
    assert names == ["01_users.sql", "02_posts.sql", "03_comments.sql"]


def test_find_seed_files_empty_directory(tmp_path):
    """Test discovery in empty directory returns no files."""
    seeds_dir = tmp_path / "db" / "seeds"
    seeds_dir.mkdir(parents=True)

    applier = SeedApplier(seeds_dir=seeds_dir)
    files = applier.find_seed_files()

    assert len(files) == 0


def test_find_seed_files_non_sql_ignored(tmp_path):
    """Test that non-SQL files are ignored."""
    seeds_dir = tmp_path / "db" / "seeds"
    seeds_dir.mkdir(parents=True)

    # Create mixed file types
    (seeds_dir / "01_users.sql").write_text("INSERT INTO users VALUES (1)")
    (seeds_dir / "readme.md").write_text("# Seed files")
    (seeds_dir / "config.yaml").write_text("config: value")
    (seeds_dir / "02_posts.sql").write_text("INSERT INTO posts VALUES (1)")

    applier = SeedApplier(seeds_dir=seeds_dir)
    files = applier.find_seed_files()

    # Verify only SQL files included
    assert len(files) == 2
    assert all(f.suffix == ".sql" for f in files)


def test_seed_applier_with_env(tmp_path):
    """Test SeedApplier can be created with environment."""
    seeds_dir = tmp_path / "db" / "seeds"
    seeds_dir.mkdir(parents=True)

    # Should not raise error even with env parameter
    applier = SeedApplier(seeds_dir=seeds_dir, env="local")
    assert applier.seeds_dir == seeds_dir
    assert applier.env == "local"


def test_seed_applier_seeds_dir_required():
    """Test SeedApplier requires seeds_dir."""
    # SeedApplier should be instantiated with seeds_dir
    seeds_dir = Path("/nonexistent/path")
    applier = SeedApplier(seeds_dir=seeds_dir)
    assert applier.seeds_dir == seeds_dir


def test_find_seed_files_preserves_paths(tmp_path):
    """Test that returned paths are Path objects."""
    seeds_dir = tmp_path / "db" / "seeds"
    seeds_dir.mkdir(parents=True)
    (seeds_dir / "01_users.sql").write_text("INSERT INTO users VALUES (1)")

    applier = SeedApplier(seeds_dir=seeds_dir)
    files = applier.find_seed_files()

    assert len(files) == 1
    assert isinstance(files[0], Path)
    assert files[0].is_file()
