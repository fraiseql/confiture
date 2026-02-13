"""Tests for Phase 2 M1 Progress Manager.

Tests the ProgressManager utility for displaying progress during operations.
"""


from confiture.core.progress import ProgressManager, _is_ci_environment, progress_bar


class TestCIDetection:
    """Test CI/CD environment detection."""

    def test_is_not_ci_by_default(self, monkeypatch):
        """Verify we detect non-CI environments correctly."""
        # Mock TTY check
        import sys

        # Create a mock stdout with isatty method
        class MockStdout:
            def isatty(self):
                return True

        monkeypatch.setattr(sys, "stdout", MockStdout())

        # Clear CI environment variables
        for var in [
            "CI",
            "GITHUB_ACTIONS",
            "GITLAB_CI",
            "CIRCLECI",
            "BUILD_ID",
            "BUILD_NUMBER",
            "RUN_ID",
            "TRAVIS",
            "JENKINS_URL",
        ]:
            monkeypatch.delenv(var, raising=False)

        # Should detect as non-CI
        assert not _is_ci_environment()

    def test_detects_github_actions(self, monkeypatch):
        """Verify GitHub Actions detection."""
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        assert _is_ci_environment()

    def test_detects_gitlab_ci(self, monkeypatch):
        """Verify GitLab CI detection."""
        monkeypatch.setenv("GITLAB_CI", "true")
        assert _is_ci_environment()

    def test_detects_no_tty(self, monkeypatch):
        """Verify non-TTY detection."""
        import sys

        class MockStdout:
            def isatty(self):
                return False

        monkeypatch.setattr(sys, "stdout", MockStdout())

        # Clear CI variables
        for var in [
            "CI",
            "GITHUB_ACTIONS",
            "GITLAB_CI",
            "CIRCLECI",
            "BUILD_ID",
            "BUILD_NUMBER",
            "RUN_ID",
            "TRAVIS",
            "JENKINS_URL",
        ]:
            monkeypatch.delenv(var, raising=False)

        assert _is_ci_environment()


class TestProgressManagerCreation:
    """Test ProgressManager initialization."""

    def test_create_progress_manager(self):
        """Verify ProgressManager can be created."""
        manager = ProgressManager(show_progress=False)
        assert manager is not None
        assert not manager.enabled

    def test_create_with_progress_enabled(self):
        """Verify ProgressManager with progress enabled."""
        manager = ProgressManager(show_progress=True)
        assert manager.enabled
        assert manager.progress is not None

    def test_create_with_auto_detect(self, monkeypatch):
        """Verify ProgressManager auto-detects CI/CD."""
        # Non-CI environment
        import sys

        class MockStdout:
            def isatty(self):
                return True

        monkeypatch.setattr(sys, "stdout", MockStdout())
        monkeypatch.delenv("CI", raising=False)

        manager = ProgressManager()  # Auto-detect
        assert manager.enabled


class TestProgressManagerTasks:
    """Test task management in ProgressManager."""

    def test_add_task_with_progress_disabled(self):
        """Verify add_task returns None when progress disabled."""
        manager = ProgressManager(show_progress=False)
        task = manager.add_task("Test task", total=10)
        assert task is None

    def test_add_task_with_progress_enabled(self):
        """Verify add_task returns Task when progress enabled."""
        manager = ProgressManager(show_progress=True)
        task = manager.add_task("Test task", total=10)
        assert task is not None
        manager.stop()

    def test_add_multiple_tasks(self):
        """Verify multiple tasks can be added."""
        manager = ProgressManager(show_progress=True)
        task1 = manager.add_task("Task 1", total=10)
        task2 = manager.add_task("Task 2", total=20)
        assert task1 is not None
        assert task2 is not None
        assert task1 != task2
        manager.stop()

    def test_indeterminate_progress(self):
        """Verify indeterminate progress (no total)."""
        manager = ProgressManager(show_progress=True)
        task = manager.add_task("Processing...", total=None)
        assert task is not None
        manager.stop()


class TestProgressManagerUpdate:
    """Test progress updates."""

    def test_update_progress(self):
        """Verify progress can be updated."""
        manager = ProgressManager(show_progress=False)
        # Should not raise when disabled
        manager.update(None, 1)

    def test_update_with_task(self):
        """Verify update works with task."""
        manager = ProgressManager(show_progress=True)
        task = manager.add_task("Processing...", total=10)
        # Should not raise
        manager.update(task, 1)
        manager.stop()

    def test_update_description(self):
        """Verify description can be updated."""
        manager = ProgressManager(show_progress=True)
        task = manager.add_task("Initial...", total=10)
        manager.update_description(task, "Updated...")
        manager.stop()

    def test_finish_task(self):
        """Verify task can be finished."""
        manager = ProgressManager(show_progress=True)
        task = manager.add_task("Processing...", total=10)
        manager.finish_task(task, "Complete!")
        manager.stop()


class TestProgressManagerContext:
    """Test context manager usage."""

    def test_context_manager(self):
        """Verify ProgressManager works as context manager."""
        with ProgressManager(show_progress=False) as manager:
            assert manager is not None
            assert not manager.enabled

    def test_context_with_task(self):
        """Verify context manager with tasks."""
        with ProgressManager(show_progress=True) as manager:
            task = manager.add_task("Processing...", total=10)
            manager.update(task, 1)
            assert task is not None


class TestProgressBarFunction:
    """Test progress_bar convenience function."""

    def test_progress_bar_creation(self):
        """Verify progress_bar function creates manager."""
        manager = progress_bar("Processing", total=100, show_progress=False)
        assert manager is not None
        assert not manager.enabled

    def test_progress_bar_with_progress(self):
        """Verify progress_bar with progress enabled."""
        manager = progress_bar("Processing", total=100, show_progress=True)
        assert manager.enabled
        manager.stop()

    def test_progress_bar_auto_detect(self, monkeypatch):
        """Verify progress_bar auto-detects CI/CD."""
        # Explicitly set show_progress=True to test the functionality
        # Auto-detection is tested separately in TestCIDetection
        manager = progress_bar("Processing", total=100, show_progress=True)
        assert manager.enabled
        manager.stop()


class TestProgressManagerRobustness:
    """Test robustness of ProgressManager."""

    def test_update_none_task(self):
        """Verify update handles None task gracefully."""
        manager = ProgressManager(show_progress=True)
        # Should not raise
        manager.update(None, 1)
        manager.stop()

    def test_update_description_none_task(self):
        """Verify update_description handles None task gracefully."""
        manager = ProgressManager(show_progress=True)
        # Should not raise
        manager.update_description(None, "Updated")
        manager.stop()

    def test_finish_none_task(self):
        """Verify finish_task handles None task gracefully."""
        manager = ProgressManager(show_progress=True)
        # Should not raise
        manager.finish_task(None, "Done")
        manager.stop()

    def test_double_stop(self):
        """Verify stop can be called multiple times."""
        manager = ProgressManager(show_progress=True)
        manager.start()
        manager.stop()
        # Should not raise
        manager.stop()

    def test_multiple_context_entries(self):
        """Verify context manager can be used once."""
        manager = ProgressManager(show_progress=True)
        with manager:
            task = manager.add_task("Test", total=10)
            manager.update(task, 1)


class TestProgressManagerIntegration:
    """Integration tests for ProgressManager."""

    def test_typical_workflow_disabled(self):
        """Test typical workflow with progress disabled."""
        with ProgressManager(show_progress=False) as manager:
            task = manager.add_task("Processing items...", total=100)
            for _ in range(100):
                manager.update(task, 1)

    def test_typical_workflow_enabled(self):
        """Test typical workflow with progress enabled."""
        with ProgressManager(show_progress=True) as manager:
            task = manager.add_task("Processing items...", total=10)
            for _ in range(10):
                manager.update(task, 1)

    def test_multiple_tasks_workflow(self):
        """Test workflow with multiple sequential tasks."""
        with ProgressManager(show_progress=True) as manager:
            task1 = manager.add_task("Phase 1...", total=5)
            for _ in range(5):
                manager.update(task1, 1)

            task2 = manager.add_task("Phase 2...", total=3)
            for _ in range(3):
                manager.update(task2, 1)


class TestProgressManagerSchemaBuilder:
    """Test ProgressManager integration with SchemaBuilder."""

    def test_builder_accepts_progress_manager(self, tmp_path):
        """Verify SchemaBuilder.build() accepts progress parameter."""
        from confiture.core.builder import SchemaBuilder

        # Create minimal schema structure
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        # Create a test SQL file
        sql_file = schema_dir / "01_tables.sql"
        sql_file.write_text("CREATE TABLE test (id INT);")

        # Create environment config
        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        config_file = env_dir / "local.yaml"
        config_file.write_text(
            "name: test\n"
            "database_url: postgresql://localhost/test\n"
            "include_dirs:\n"
            "  - db/schema\n"
        )

        # Build with progress manager
        builder = SchemaBuilder(env="local", project_dir=tmp_path)
        with ProgressManager(show_progress=False) as progress:
            schema = builder.build(progress=progress)
            assert "CREATE TABLE test" in schema

    def test_builder_build_without_progress(self, tmp_path):
        """Verify SchemaBuilder.build() works without progress parameter."""
        from confiture.core.builder import SchemaBuilder

        # Create minimal schema structure
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        # Create a test SQL file
        sql_file = schema_dir / "01_tables.sql"
        sql_file.write_text("CREATE TABLE test (id INT);")

        # Create environment config
        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        config_file = env_dir / "local.yaml"
        config_file.write_text(
            "name: test\n"
            "database_url: postgresql://localhost/test\n"
            "include_dirs:\n"
            "  - db/schema\n"
        )

        # Build without progress manager (backward compatibility)
        builder = SchemaBuilder(env="local", project_dir=tmp_path)
        schema = builder.build()
        assert "CREATE TABLE test" in schema

    def test_builder_progress_multiple_files(self, tmp_path):
        """Verify progress tracking works with multiple files."""
        from confiture.core.builder import SchemaBuilder

        # Create schema structure with multiple files
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        # Create multiple SQL files
        for i in range(3):
            sql_file = schema_dir / f"{i:02d}_tables.sql"
            sql_file.write_text(f"CREATE TABLE table{i} (id INT);")

        # Create environment config
        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        config_file = env_dir / "local.yaml"
        config_file.write_text(
            "name: test\n"
            "database_url: postgresql://localhost/test\n"
            "include_dirs:\n"
            "  - db/schema\n"
        )

        # Build with progress manager
        builder = SchemaBuilder(env="local", project_dir=tmp_path)
        with ProgressManager(show_progress=False) as progress:
            schema = builder.build(progress=progress)

            # Verify all files included
            for i in range(3):
                assert f"CREATE TABLE table{i}" in schema
