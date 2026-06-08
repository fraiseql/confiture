"""Unit tests for the test-db provisioner's pure logic (P2).

Identifier validation, SQL composition, and template-status classification are
testable without a database. DB-touching behaviour is integration-tested.
"""

from __future__ import annotations

import pytest

from confiture.core.test_db import (
    TemplateState,
    TestDbProvisioner,
    _classify_template,
    _clone_sql,
    _comment_sql,
    _create_db_sql,
    _managed_kind,
    _validate_identifier,
)
from confiture.exceptions import ConfigurationError

# ---------------------------------------------------------------------------
# Identifier validation (injection guard)
# ---------------------------------------------------------------------------


class TestValidateIdentifier:
    @pytest.mark.parametrize("name", ["t", "t_gw0", "confiture_template", "App_DB_1", "_x"])
    def test_accepts_valid(self, name: str) -> None:
        _validate_identifier(name)  # does not raise

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "1abc",  # leading digit
            "a b",  # space
            'a"; DROP DATABASE postgres; --',  # injection attempt
            "a-b",  # hyphen
            "a" * 64,  # too long (>63)
            "naïve",  # non-ascii
        ],
    )
    def test_rejects_invalid(self, name: str) -> None:
        with pytest.raises(ConfigurationError):
            _validate_identifier(name)


# ---------------------------------------------------------------------------
# SQL composition — identifiers are quoted, never interpolated
# ---------------------------------------------------------------------------


class TestSqlComposition:
    def test_clone_sql_quotes_identifiers(self) -> None:
        assert (
            _clone_sql("t_gw0", "tmpl").as_string(None)
            == 'CREATE DATABASE "t_gw0" WITH TEMPLATE "tmpl"'
        )

    def test_create_db_sql(self) -> None:
        assert _create_db_sql("tmpl").as_string(None) == 'CREATE DATABASE "tmpl"'

    def test_comment_sql_quotes_name_and_literal(self) -> None:
        sql = _comment_sql("tmpl", "confiture:template:deadbeef").as_string(None)
        assert sql == "COMMENT ON DATABASE \"tmpl\" IS 'confiture:template:deadbeef'"


# ---------------------------------------------------------------------------
# Template-status classification (pure)
# ---------------------------------------------------------------------------


class TestClassifyTemplate:
    def test_absent_when_db_missing(self) -> None:
        st = _classify_template(comment=None, current_hash="h1", exists=False)
        assert st.state is TemplateState.ABSENT

    def test_current_when_hash_matches(self) -> None:
        st = _classify_template(comment="confiture:template:h1", current_hash="h1", exists=True)
        assert st.state is TemplateState.CURRENT
        assert st.stored_hash == "h1"

    def test_stale_when_hash_differs(self) -> None:
        st = _classify_template(comment="confiture:template:OLD", current_hash="NEW", exists=True)
        assert st.state is TemplateState.STALE
        assert st.stored_hash == "OLD"

    def test_absent_when_db_exists_but_unmanaged(self) -> None:
        st = _classify_template(comment=None, current_hash="h1", exists=True)
        assert st.state is TemplateState.ABSENT


class TestManagedKind:
    def test_template(self) -> None:
        assert _managed_kind("confiture:template:abc") == "template"

    def test_clone(self) -> None:
        assert _managed_kind("confiture:clone:tmpl") == "clone"

    def test_unmanaged(self) -> None:
        assert _managed_kind(None) is None
        assert _managed_kind("some user comment") is None


# ---------------------------------------------------------------------------
# Provisioner wiring (maintenance URL derivation)
# ---------------------------------------------------------------------------


class TestProvisionerInit:
    def test_derives_maintenance_url(self) -> None:
        prov = TestDbProvisioner("postgresql://localhost/myapp")
        assert prov.maintenance_url == "postgresql://localhost/postgres"
