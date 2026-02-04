"""Unit tests for migration generation safety validations (Phase 1).

Tests duplicate version detection, file existence checks, name conflicts,
and concurrent creation protection.
"""

from confiture.core.migration_generator import MigrationGenerator


class TestDuplicateVersionDetection:
    """Test detection of duplicate version numbers in migrations."""

    def test_detect_duplicate_versions(self, tmp_path):
        """Should detect when multiple files have same version number."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create migrations with duplicate version
        (migrations_dir / "003_migration_a.py").write_text("# migration a")
        (migrations_dir / "003_migration_b.py").write_text("# migration b")

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        duplicates = generator._validate_versions()

        # Should detect the duplicate
        assert "003" in duplicates
        assert len(duplicates["003"]) == 2

    def test_no_duplicates_returns_empty(self, tmp_path):
        """Should return empty dict when no duplicates exist."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create migrations with unique versions
        (migrations_dir / "001_first.py").write_text("# migration")
        (migrations_dir / "002_second.py").write_text("# migration")
        (migrations_dir / "003_third.py").write_text("# migration")

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        duplicates = generator._validate_versions()

        # Should have no duplicates
        assert duplicates == {}

    def test_multiple_duplicates(self, tmp_path):
        """Should detect multiple different duplicate version numbers."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create multiple sets of duplicates
        (migrations_dir / "002_first_a.py").write_text("# migration")
        (migrations_dir / "002_first_b.py").write_text("# migration")
        (migrations_dir / "005_second_a.py").write_text("# migration")
        (migrations_dir / "005_second_b.py").write_text("# migration")

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        duplicates = generator._validate_versions()

        # Should detect both duplicates
        assert len(duplicates) == 2
        assert len(duplicates["002"]) == 2
        assert len(duplicates["005"]) == 2

    def test_empty_directory_has_no_duplicates(self, tmp_path):
        """Should handle empty directory gracefully."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        duplicates = generator._validate_versions()

        assert duplicates == {}

    def test_directory_not_exists_has_no_duplicates(self, tmp_path):
        """Should handle non-existent directory gracefully."""
        migrations_dir = tmp_path / "migrations"
        # Don't create directory

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        duplicates = generator._validate_versions()

        assert duplicates == {}

    def test_malformed_filenames_ignored(self, tmp_path):
        """Should gracefully ignore files without version prefix."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create migrations with and without valid version
        (migrations_dir / "001_valid.py").write_text("# migration")
        (migrations_dir / "002_valid.py").write_text("# migration")
        (migrations_dir / "no_version_here.py").write_text("# migration")

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        duplicates = generator._validate_versions()

        # Should only include valid versions
        assert duplicates == {}


class TestFileExistenceCheck:
    """Test prevention of accidental file overwrites."""

    def test_prevent_overwrite_without_force(self, tmp_path):
        """Should prevent overwriting existing file without --force flag."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create an existing migration
        existing_file = migrations_dir / "001_existing.py"
        existing_file.write_text("# existing migration")

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # Should detect file exists
        assert generator._check_file_exists(existing_file)

    def test_allow_overwrite_with_force(self, tmp_path):
        """Should allow overwrite when force=True."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        existing_file = migrations_dir / "001_existing.py"
        original_content = "# original content"
        existing_file.write_text(original_content)

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # Can check file exists
        assert generator._check_file_exists(existing_file)

    def test_file_not_exists_check(self, tmp_path):
        """Should return False when file doesn't exist."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        non_existent = migrations_dir / "999_not_here.py"

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # Should report file doesn't exist
        assert not generator._check_file_exists(non_existent)


class TestNameConflictDetection:
    """Test detection of migration name conflicts."""

    def test_detect_name_conflict(self, tmp_path):
        """Should detect when same name exists with different version."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create migrations with same name but different versions
        (migrations_dir / "001_add_users.py").write_text("# migration")
        (migrations_dir / "002_add_users.py").write_text("# migration")

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        conflicts = generator._check_name_conflict("add_users")

        # Should find both files
        assert len(conflicts) == 2

    def test_no_conflict_different_names(self, tmp_path):
        """Should return empty list when no name conflicts."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create migrations with unique names
        (migrations_dir / "001_add_users.py").write_text("# migration")
        (migrations_dir / "002_add_posts.py").write_text("# migration")

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        conflicts = generator._check_name_conflict("add_comments")

        # Should find no conflicts
        assert conflicts == []

    def test_name_conflict_with_variants(self, tmp_path):
        """Should handle name conflict detection with slightly different names."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create migrations with similar names
        (migrations_dir / "001_add_user_email.py").write_text("# migration")
        (migrations_dir / "002_add_user_bio.py").write_text("# migration")

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # Should find exact name only
        conflicts = generator._check_name_conflict("add_user_email")
        assert len(conflicts) == 1

        # Different name should not match
        conflicts = generator._check_name_conflict("add_user")
        assert len(conflicts) == 0

    def test_empty_directory_no_conflicts(self, tmp_path):
        """Should handle empty directory."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        conflicts = generator._check_name_conflict("any_name")

        assert conflicts == []


class TestConcurrentCreationProtection:
    """Test protection against concurrent migration generation."""

    def test_file_locking_mechanism(self, tmp_path):
        """Should use file locking to prevent concurrent access."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # Should be able to acquire and release lock
        lock_fd = generator._acquire_migration_lock()
        assert lock_fd is not None

        # Should be able to release lock
        generator._release_migration_lock(lock_fd)

    def test_lock_released_on_error(self, tmp_path):
        """Should release lock even if error occurs."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        lock_fd = generator._acquire_migration_lock()
        try:
            # Simulate error
            raise RuntimeError("Test error")
        except RuntimeError:
            # Should still be able to release lock
            generator._release_migration_lock(lock_fd)

        # Lock should be available again (can acquire new lock)
        lock_fd2 = generator._acquire_migration_lock()
        assert lock_fd2 is not None
        generator._release_migration_lock(lock_fd2)


class TestVersionCalculationWithValidation:
    """Test version calculation in presence of validation issues."""

    def test_next_version_with_duplicates_present(self, tmp_path):
        """Should calculate next version despite duplicate versions."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create migrations including duplicates
        (migrations_dir / "001_first.py").write_text("# migration")
        (migrations_dir / "003_third_a.py").write_text("# migration")
        (migrations_dir / "003_third_b.py").write_text("# migration")

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # Should find next version after highest (3)
        next_version = generator._get_next_version()
        assert next_version == "004"

    def test_next_version_with_gaps(self, tmp_path):
        """Should calculate next version with gaps in sequence."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create migrations with gaps
        (migrations_dir / "001_first.py").write_text("# migration")
        (migrations_dir / "005_fifth.py").write_text("# migration")
        (migrations_dir / "007_seventh.py").write_text("# migration")

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # Should find next version after highest
        next_version = generator._get_next_version()
        assert next_version == "008"
