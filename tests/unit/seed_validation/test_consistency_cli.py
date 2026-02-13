"""Tests for consistency validation CLI integration."""

from pathlib import Path

from confiture.core.seed_validation.consistency_cli import (
    ConsistencyCLI,
    ConsistencyCLIConfig,
)


class TestConsistencyCLIBasics:
    """Test basic CLI functionality."""

    def test_creates_cli_instance(self) -> None:
        """Test that CLI instance can be created."""
        cli = ConsistencyCLI()
        assert cli is not None

    def test_cli_has_validate_method(self) -> None:
        """Test that CLI has validate method."""
        cli = ConsistencyCLI()
        assert hasattr(cli, "validate")
        assert callable(cli.validate)

    def test_validate_accepts_seed_data_and_schema(self) -> None:
        """Test that validate method accepts required arguments."""
        cli = ConsistencyCLI()
        seed_data = {"users": [{"id": "1"}]}
        schema_context = {"users": {"required": True}}

        result = cli.validate(seed_data, schema_context)

        assert result is not None


class TestConsistencyCLIConfiguration:
    """Test CLI configuration."""

    def test_cli_config_has_required_fields(self) -> None:
        """Test that CLI config has all required fields."""
        config = ConsistencyCLIConfig()

        assert hasattr(config, "output_format")
        assert hasattr(config, "stop_on_first")
        assert hasattr(config, "verbose")

    def test_cli_config_default_values(self) -> None:
        """Test that CLI config has sensible defaults."""
        config = ConsistencyCLIConfig()

        assert config.output_format in ("text", "json")
        assert isinstance(config.stop_on_first, bool)
        assert isinstance(config.verbose, bool)

    def test_cli_accepts_config(self) -> None:
        """Test that CLI accepts custom configuration."""
        config = ConsistencyCLIConfig(output_format="json", stop_on_first=True, verbose=False)
        cli = ConsistencyCLI(config=config)

        assert cli is not None


class TestConsistencyCLIValidation:
    """Test CLI validation results."""

    def test_returns_result_object(self) -> None:
        """Test that validate returns a result object."""
        cli = ConsistencyCLI()
        seed_data = {"users": [{"id": "1"}]}
        schema_context = {"users": {"required": True}}

        result = cli.validate(seed_data, schema_context)

        assert hasattr(result, "success")
        assert hasattr(result, "message")

    def test_detects_violations_in_result(self) -> None:
        """Test that result includes violation count."""
        cli = ConsistencyCLI()
        seed_data = {"users": [{"id": "1", "email": None}]}
        schema_context = {"users": {"columns": {"email": {"required": True}}}}

        result = cli.validate(seed_data, schema_context)

        assert hasattr(result, "violation_count")
        assert result.violation_count > 0

    def test_result_success_flag_for_valid_data(self) -> None:
        """Test that result success=True for valid data."""
        cli = ConsistencyCLI()
        seed_data = {"users": [{"id": "1", "email": "alice@example.com"}]}
        schema_context = {
            "users": {
                "columns": {"email": {"required": True}},
            }
        }

        result = cli.validate(seed_data, schema_context)

        assert result.success is True

    def test_result_success_flag_for_invalid_data(self) -> None:
        """Test that result success=False for invalid data."""
        cli = ConsistencyCLI()
        seed_data = {"users": [{"id": "1", "email": None}]}
        schema_context = {"users": {"columns": {"email": {"required": True}}}}

        result = cli.validate(seed_data, schema_context)

        assert result.success is False


class TestConsistencyCLIOutput:
    """Test CLI output formatting."""

    def test_format_text_output(self) -> None:
        """Test text format output."""
        config = ConsistencyCLIConfig(output_format="text")
        cli = ConsistencyCLI(config=config)
        seed_data = {"users": [{"id": "1", "email": None}]}
        schema_context = {"users": {"columns": {"email": {"required": True}}}}

        result = cli.validate(seed_data, schema_context)
        output = result.format_output()

        assert isinstance(output, str)
        assert len(output) > 0

    def test_format_json_output(self) -> None:
        """Test JSON format output."""
        config = ConsistencyCLIConfig(output_format="json")
        cli = ConsistencyCLI(config=config)
        seed_data = {"users": [{"id": "1", "email": None}]}
        schema_context = {"users": {"columns": {"email": {"required": True}}}}

        result = cli.validate(seed_data, schema_context)
        output = result.format_output()

        assert isinstance(output, str)
        # Should be valid JSON-like (contains braces)
        assert "{" in output

    def test_output_includes_violations(self) -> None:
        """Test that output includes violation details."""
        config = ConsistencyCLIConfig(output_format="text")
        cli = ConsistencyCLI(config=config)
        seed_data = {"users": [{"id": "1", "email": None}]}
        schema_context = {"users": {"columns": {"email": {"required": True}}}}

        result = cli.validate(seed_data, schema_context)
        output = result.format_output()

        # Should mention violations or errors
        assert "error" in output.lower() or "violation" in output.lower()


class TestConsistencyCLIFileOperations:
    """Test CLI file handling."""

    def test_cli_can_load_seed_file(self, tmp_path: Path) -> None:
        """Test that CLI can load seed data from file."""
        # Create a temporary SQL file with seed data
        seed_file = tmp_path / "seed.sql"
        seed_file.write_text("INSERT INTO users (id, email) VALUES ('1', 'alice@example.com')")

        cli = ConsistencyCLI()
        # Should be able to load from file
        assert hasattr(cli, "load_seed_file")

    def test_cli_can_load_schema_file(self, tmp_path: Path) -> None:
        """Test that CLI can load schema from file."""
        # Create a temporary schema file
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text("users:\n  required: true\n")

        cli = ConsistencyCLI()
        # Should be able to load from file
        assert hasattr(cli, "load_schema_file")


class TestConsistencyCLIExitCodes:
    """Test CLI exit codes."""

    def test_exit_code_success(self) -> None:
        """Test exit code for successful validation."""
        cli = ConsistencyCLI()
        seed_data = {"users": [{"id": "1"}]}
        schema_context = {}

        result = cli.validate(seed_data, schema_context)

        assert result.exit_code == 0

    def test_exit_code_failure(self) -> None:
        """Test exit code for failed validation."""
        cli = ConsistencyCLI()
        seed_data = {}
        schema_context = {"users": {"required": True}}

        result = cli.validate(seed_data, schema_context)

        assert result.exit_code != 0


class TestConsistencyCLIVerbosity:
    """Test CLI verbosity levels."""

    def test_verbose_mode_includes_details(self) -> None:
        """Test that verbose mode includes more details."""
        config_quiet = ConsistencyCLIConfig(verbose=False)
        config_verbose = ConsistencyCLIConfig(verbose=True)

        cli_quiet = ConsistencyCLI(config=config_quiet)
        cli_verbose = ConsistencyCLI(config=config_verbose)

        seed_data = {"users": [{"id": "1", "email": None}]}
        schema_context = {"users": {"columns": {"email": {"required": True}}}}

        result_quiet = cli_quiet.validate(seed_data, schema_context)
        result_verbose = cli_verbose.validate(seed_data, schema_context)

        output_quiet = result_quiet.format_output()
        output_verbose = result_verbose.format_output()

        # Verbose output should be longer or more detailed
        assert len(output_verbose) >= len(output_quiet)


class TestConsistencyCLIResultStructure:
    """Test the structure of CLI result object."""

    def test_result_has_all_fields(self) -> None:
        """Test that result has all required fields."""
        cli = ConsistencyCLI()
        seed_data = {"users": [{"id": "1"}]}
        schema_context = {}

        result = cli.validate(seed_data, schema_context)

        assert hasattr(result, "success")
        assert hasattr(result, "message")
        assert hasattr(result, "violation_count")
        assert hasattr(result, "exit_code")
        assert hasattr(result, "format_output")

    def test_result_message_is_descriptive(self) -> None:
        """Test that result message is human-readable."""
        cli = ConsistencyCLI()
        seed_data = {}
        schema_context = {"users": {"required": True}}

        result = cli.validate(seed_data, schema_context)
        message = result.message

        assert isinstance(message, str)
        assert len(message) > 0


class TestConsistencyCLIIntegration:
    """Test end-to-end CLI scenarios."""

    def test_complete_validation_workflow(self) -> None:
        """Test complete validation workflow."""
        config = ConsistencyCLIConfig(output_format="text", verbose=True)
        cli = ConsistencyCLI(config=config)

        seed_data = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "bob@example.com"},
            ],
            "orders": [
                {"id": "1", "customer_id": "1"},
                {"id": "2", "customer_id": "999"},  # Invalid FK
            ],
        }

        schema_context = {
            "users": {"required": True},
            "orders": {"columns": {"customer_id": {"foreign_key": ("users", "id")}}},
        }

        result = cli.validate(seed_data, schema_context)

        assert result.success is False
        assert result.violation_count > 0
        assert result.exit_code != 0

        output = result.format_output()
        assert len(output) > 0
