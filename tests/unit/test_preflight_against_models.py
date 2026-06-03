"""Unit tests for PreflightAgainstMigration and PreflightAgainstResult models."""

from confiture import PreflightAgainstMigration, PreflightAgainstResult

# ---------------------------------------------------------------------------
# PreflightAgainstMigration
# ---------------------------------------------------------------------------


def test_preflight_against_migration_success():
    m = PreflightAgainstMigration(
        version="20260428102229", name="fix_stats", success=True, execution_time_ms=120
    )
    assert m.success is True
    assert m.skipped is False
    assert m.error is None


def test_preflight_against_migration_failure():
    m = PreflightAgainstMigration(
        version="20260428235025",
        name="tv_dims",
        success=False,
        error="cannot change name of input parameter",
    )
    assert m.success is False
    assert m.skipped is False
    assert m.error is not None
    assert "input parameter" in m.error


def test_preflight_against_migration_skipped():
    m = PreflightAgainstMigration(
        version="20260428000000",
        name="add_idx",
        success=False,
        skipped=True,
        skipped_reason="non-transactional: cannot run inside SAVEPOINT",
    )
    assert m.skipped is True
    assert m.error is None


def test_to_dict_has_all_keys():
    m = PreflightAgainstMigration(version="001", name="a", success=True)
    d = m.to_dict()
    assert set(d) == {
        "version",
        "name",
        "success",
        "error",
        "skipped",
        "skipped_reason",
        "execution_time_ms",
    }


# ---------------------------------------------------------------------------
# PreflightAgainstResult
# ---------------------------------------------------------------------------


def test_all_passed_true():
    result = PreflightAgainstResult(
        migrations=[
            PreflightAgainstMigration("001", "a", True),
            PreflightAgainstMigration("002", "b", True),
        ],
        against_url="postgresql://localhost/preflight",
    )
    assert result.all_passed is True
    assert result.failures == []
    assert result.has_skipped is False


def test_all_passed_ignores_skipped():
    """Skipped migrations are neutral — they do not make all_passed False."""
    result = PreflightAgainstResult(
        migrations=[
            PreflightAgainstMigration("001", "a", True),
            PreflightAgainstMigration(
                "002",
                "b",
                False,
                skipped=True,
                skipped_reason="non-transactional",
            ),
        ],
        against_url="postgresql://localhost/preflight",
    )
    assert result.all_passed is True
    assert result.has_skipped is True
    assert result.failures == []
    assert len(result.skipped_migrations) == 1


def test_all_passed_false_on_actual_failure():
    result = PreflightAgainstResult(
        migrations=[
            PreflightAgainstMigration("001", "a", True),
            PreflightAgainstMigration("002", "b", False, error="syntax error"),
        ],
        against_url="postgresql://localhost/preflight",
    )
    assert result.all_passed is False
    assert len(result.failures) == 1


def test_db_consumed_default_false():
    result = PreflightAgainstResult(
        migrations=[PreflightAgainstMigration("001", "a", True)],
        against_url="postgresql://localhost/preflight",
    )
    assert result.db_consumed is False


def test_to_dict_redacts_password_keeps_username():
    result = PreflightAgainstResult(
        migrations=[PreflightAgainstMigration("001", "a", True)],
        against_url="postgresql://app_user:s3cr3t@localhost:5432/preflight",
    )
    d = result.to_dict()
    assert "s3cr3t" not in d["against_url"]
    assert "app_user" in d["against_url"]
    assert "localhost" in d["against_url"]


def test_to_dict_no_password_unchanged():
    result = PreflightAgainstResult(
        migrations=[PreflightAgainstMigration("001", "a", True)],
        against_url="postgresql://localhost/preflight",
    )
    assert result.to_dict()["against_url"] == "postgresql://localhost/preflight"


def test_to_dict_url_user_no_password_unchanged():
    """Username without password → URL returned as-is."""
    result = PreflightAgainstResult(
        migrations=[PreflightAgainstMigration("001", "a", True)],
        against_url="postgresql://app_user@localhost/preflight",
    )
    assert result.to_dict()["against_url"] == "postgresql://app_user@localhost/preflight"


def test_to_dict_url_password_no_username_strips_password():
    """Password without username → password removed, host preserved."""
    result = PreflightAgainstResult(
        migrations=[PreflightAgainstMigration("001", "a", True)],
        against_url="postgresql://:s3cr3t@localhost/preflight",
    )
    d = result.to_dict()
    assert "s3cr3t" not in d["against_url"]
    assert "localhost" in d["against_url"]


def test_to_dict_structure():
    result = PreflightAgainstResult(
        migrations=[
            PreflightAgainstMigration("001", "a", True),
            PreflightAgainstMigration(
                "002",
                "b",
                False,
                skipped=True,
                skipped_reason="non-transactional",
            ),
        ],
        against_url="postgresql://localhost/preflight",
        db_consumed=False,
    )
    d = result.to_dict()
    assert d["all_passed"] is True
    assert d["total"] == 2
    assert d["passed"] == 1
    assert d["failed"] == 0
    assert d["skipped"] == 1
    assert d["db_consumed"] is False
    assert len(d["migrations"]) == 2


# ---------------------------------------------------------------------------
# PreflightAgainstResult.replay_issues  (issue #151)
# ---------------------------------------------------------------------------


def test_replay_issues_empty_when_all_pass():
    """No failures → no replay issues."""
    result = PreflightAgainstResult(
        migrations=[
            PreflightAgainstMigration("001", "a", True),
            PreflightAgainstMigration("002", "b", True),
        ],
        against_url="postgresql://localhost/preflight",
    )
    assert result.replay_issues == []


def test_replay_issues_one_per_failure():
    """Each failed (non-skipped) migration yields one PFLIGHT_REPLAY_FAILED issue."""
    result = PreflightAgainstResult(
        migrations=[
            PreflightAgainstMigration("001", "a", True),
            PreflightAgainstMigration("002", "b", False, error="syntax error"),
            PreflightAgainstMigration("003", "c", False, error="missing column"),
        ],
        against_url="postgresql://localhost/preflight",
    )
    issues = result.replay_issues
    assert len(issues) == 2
    assert all(i.code == "PFLIGHT_REPLAY_FAILED" for i in issues)
    assert all(i.severity == "error" for i in issues)
    assert {i.migration for i in issues} == {"002", "003"}


def test_replay_issues_skips_skipped():
    """Skipped migrations are neutral — they produce no replay issue."""
    result = PreflightAgainstResult(
        migrations=[
            PreflightAgainstMigration("001", "a", True),
            PreflightAgainstMigration(
                "002",
                "b",
                False,
                skipped=True,
                skipped_reason="non-transactional",
            ),
        ],
        against_url="postgresql://localhost/preflight",
    )
    assert result.replay_issues == []


def test_replay_issue_carries_error_in_details():
    """The DB error is preserved under details['error']; actionable comes from PFLIGHT_CODES."""
    result = PreflightAgainstResult(
        migrations=[
            PreflightAgainstMigration(
                "20260501120000", "tv_dims", False, error="cannot change name of input parameter"
            ),
        ],
        against_url="postgresql://localhost/preflight",
    )
    (issue,) = result.replay_issues
    assert issue.migration == "20260501120000"
    assert issue.details["error"] == "cannot change name of input parameter"
    assert issue.actionable is not None
    assert "20260501120000" in issue.message


def test_replay_issue_no_error_yields_empty_details():
    """A failure with no error string still produces an issue, with empty details."""
    result = PreflightAgainstResult(
        migrations=[PreflightAgainstMigration("002", "b", False, error=None)],
        against_url="postgresql://localhost/preflight",
    )
    (issue,) = result.replay_issues
    assert issue.details == {}
