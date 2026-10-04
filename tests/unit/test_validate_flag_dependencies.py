"""``validate_flag_dependencies`` — modifiers name the check they modify.

The CLI guard test can only see the exit code (the error console is not
captured by the runner), so the message is pinned here, on the function.
"""

from pathlib import Path

import pytest

from confiture.cli.commands.validate_checks import ValidateOptions, validate_flag_dependencies
from confiture.exceptions import ConfigurationError


def _opts(**flags: bool | str) -> ValidateOptions:
    return ValidateOptions(
        format_output="text",
        json_mode=False,
        migrations_dir=Path("db/migrations"),
        config=Path("confiture.yaml"),
        git_env="local",
        schema_file=None,
        scratch_url=None,
        schemas="public",
        ssh_via=None,
        **flags,
    )


def test_fail_on_unanalyzable_requires_idempotent() -> None:
    with pytest.raises(ConfigurationError, match=r"--fail-on-unanalyzable requires --idempotent"):
        validate_flag_dependencies(_opts(fail_on_unanalyzable=True))


def test_fail_on_unanalyzable_with_idempotent_is_legal() -> None:
    assert validate_flag_dependencies(_opts(fail_on_unanalyzable=True, idempotent=True)) is None


def test_check_body_still_requires_check_signatures() -> None:
    with pytest.raises(ConfigurationError, match=r"--check-body requires --check-signatures"):
        validate_flag_dependencies(_opts(check_body=True))


def test_extra_objects_requires_check_live_drift() -> None:
    with pytest.raises(ConfigurationError, match=r"--extra-objects requires --check-live-drift"):
        validate_flag_dependencies(_opts(extra_objects="all"))


def test_extra_objects_with_check_live_drift_is_legal() -> None:
    assert validate_flag_dependencies(_opts(extra_objects="all", check_live_drift=True)) is None
