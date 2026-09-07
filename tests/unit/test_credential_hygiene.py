"""A DSN password never reaches argv, a log line or an error message.

Four leaks, one rule: the only spelling of a connection URL that may leave the
process is the one :func:`confiture.url_redaction.redact_url` produces, and
the only way a password reaches a libpq client is ``PGPASSWORD``.

* the backup hook passed the full DSN to ``pg_dump`` on argv (``ps aux``);
* ``redact_url`` masked ``user:pw@`` but not the ``?password=`` query key libpq
  also accepts;
* the URL validators echoed the rejected value, password included;
* ``models/results.py`` carried its own redactor, which dropped the password
  instead of marking it — a second implementation is a second place to drift.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from confiture.config.environment import DatabaseConfig, Environment
from confiture.core.hooks.builtin.backup_hook import BackupConfig, BackupHook
from confiture.core.hooks.context import ExecutionContext, HookContext
from confiture.core.hooks.phases import HookPhase
from confiture.core.validation.config_validator import ConfigValidator
from confiture.models.results import PreflightAgainstResult
from confiture.url_redaction import redact_url, split_password

PW = "s3cr3t-pw"


# ---------------------------------------------------------------------------
# (a) pg_dump argv
# ---------------------------------------------------------------------------


class TestBackupHookArgv:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("url", "safe"),
        [
            (f"postgresql://u:{PW}@h:5432/db", "postgresql://u@h:5432/db"),
            (f"postgresql://u@h/db?password={PW}", "postgresql://u@h/db"),
        ],
        ids=["userinfo", "query-key"],
    )
    async def test_password_rides_in_pgpassword_not_argv(
        self, tmp_path, url: str, safe: str
    ) -> None:
        hook = BackupHook(BackupConfig(backup_dir=tmp_path, database_url=url, compress=False))
        context = HookContext(
            phase=HookPhase.BEFORE_EXECUTE,
            data=ExecutionContext(metadata={"migration_name": "m"}),
        )
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate.return_value = (b"-- dump", b"")

        with patch("asyncio.create_subprocess_exec", return_value=proc) as spawn:
            result = await hook.execute(context)

        assert result.success, result.error
        args, kwargs = spawn.call_args
        assert all(PW not in str(a) for a in args), args
        assert args[-1] == safe
        assert kwargs["env"]["PGPASSWORD"] == PW


# ---------------------------------------------------------------------------
# (b) the ?password= query key
# ---------------------------------------------------------------------------


class TestQueryKeyPassword:
    def test_redact_url_masks_password_query_key(self) -> None:
        assert redact_url(f"postgresql://u@h/db?password={PW}") == (
            "postgresql://u@h/db?password=***"
        )

    def test_redact_url_masks_both_spellings_and_keeps_other_params(self) -> None:
        assert redact_url(f"postgresql://u:{PW}@h/db?sslmode=require&password={PW}") == (
            "postgresql://u:***@h/db?sslmode=require&password=***"
        )

    def test_split_password_pulls_the_query_key(self) -> None:
        assert split_password(f"postgresql://u@h/db?password={PW}&sslmode=require") == (
            "postgresql://u@h/db?sslmode=require",
            PW,
        )

    def test_split_password_decodes_the_query_key(self) -> None:
        assert split_password("postgresql://u@h/db?password=p%40ss%20word") == (
            "postgresql://u@h/db",
            "p@ss word",
        )


# ---------------------------------------------------------------------------
# (c) validators echo the redacted form
# ---------------------------------------------------------------------------


class TestValidatorsRedact:
    def test_environment_rejects_without_echoing_the_password(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            Environment.model_validate(
                {
                    "name": "x",
                    "database_url": f"mysql://u:{PW}@h/db",
                    "include_dirs": ["db/schema"],
                }
            )
        text = str(excinfo.value)
        assert PW not in text
        assert "mysql://u:***@h/db" in text

    def test_database_config_from_url_rejects_without_echoing_the_password(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            DatabaseConfig.from_url(f"mysql://u:{PW}@h/db")
        assert PW not in str(excinfo.value)
        assert "***" in str(excinfo.value)

    def test_config_validator_dsn_issue_is_redacted(self) -> None:
        validator = ConfigValidator.from_flags(database_url=f"mysql://u:{PW}@h/db")
        issues = validator._validate_dsn_format(f"mysql://u:{PW}@h/db")
        assert issues and issues[0].code == "CONFIG_003"
        assert PW not in issues[0].message
        assert "***" in issues[0].message


# ---------------------------------------------------------------------------
# (d) one redactor
# ---------------------------------------------------------------------------


class TestOneRedactor:
    def test_results_model_has_no_private_redactor(self) -> None:
        assert not hasattr(PreflightAgainstResult, "_redact_url")

    def test_against_url_is_redacted_the_same_way_everywhere(self) -> None:
        result = PreflightAgainstResult(migrations=[], against_url=f"postgresql://u:{PW}@h/db")
        assert result.to_dict()["against_url"] == redact_url(f"postgresql://u:{PW}@h/db")
        assert result.to_dict()["against_url"] == "postgresql://u:***@h/db"
