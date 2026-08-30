"""Issue #211 part 2: a refusal names the marker it looked for.

``TestDbProvisioner`` declines to clobber a database that carries no confiture
management comment. The refusal is correct; the wording was not actionable.
"Not confiture-managed" is a verdict without its evidence, and the two cases a
reader must tell apart look identical from the message alone:

* a genuinely foreign database, which must not be touched, and
* confiture's own template that lost its comment to an out-of-band recreate
  (a schema-regeneration step, a manual ``CREATE DATABASE``).

Naming the COMMENT prefix it looked for — and reporting what it found instead —
separates them without reading ``_managed_kind``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from confiture.core.test_db import (
    _CLONE_PREFIX,
    _MANAGED_PREFIX,
    _TEMPLATE_PREFIX,
    TestDbProvisioner,
)
from confiture.exceptions import ConfigurationError

_URL = "postgresql://localhost/postgres"


def _provisioner_seeing(comment: str | None) -> TestDbProvisioner:
    """A provisioner whose maintenance connection reports an existing db."""
    p = TestDbProvisioner(_URL)
    p._read_comment = MagicMock(return_value=(True, comment))  # type: ignore[method-assign]
    p._maintenance_conn = MagicMock()  # type: ignore[method-assign]
    return p


class TestProvisionTemplateRefusal:
    def test_reports_a_missing_comment_as_the_evidence(self) -> None:
        provisioner = _provisioner_seeing(None)

        with pytest.raises(ConfigurationError) as exc_info:
            provisioner.provision_template("proj_test_template", schema_hash="h", schema_sql="")

        message = exc_info.value.message
        assert "no database COMMENT" in message
        assert _TEMPLATE_PREFIX in message

    def test_reports_a_foreign_comment_verbatim(self) -> None:
        provisioner = _provisioner_seeing("someone else's database")

        with pytest.raises(ConfigurationError) as exc_info:
            provisioner.provision_template("proj_test_template", schema_hash="h", schema_sql="")

        assert "someone else's database" in exc_info.value.message

    def test_hint_covers_the_out_of_band_recreate(self) -> None:
        """The safe fix when confiture's own template lost its comment is to
        drop it and let confiture re-provision — neither rename nor --force."""
        provisioner = _provisioner_seeing(None)

        with pytest.raises(ConfigurationError) as exc_info:
            provisioner.provision_template("proj_test_template", schema_hash="h", schema_sql="")

        hint = exc_info.value.resolution_hint or ""
        assert "DROP DATABASE" in hint
        assert "proj_test_template" in hint
        assert "--force" in hint

    def test_still_refuses(self) -> None:
        """The refusal itself is unchanged: no database is touched."""
        provisioner = _provisioner_seeing(None)

        with patch("confiture.core.test_db.force_drop_database") as drop:
            with pytest.raises(ConfigurationError):
                provisioner.provision_template("t", schema_hash="h", schema_sql="")

        drop.assert_not_called()

    def test_force_still_replaces(self) -> None:
        provisioner = _provisioner_seeing(None)
        with (
            patch("confiture.core.test_db.force_drop_database"),
            patch("confiture.core.test_db.apply_sql_via_psql"),
            patch.object(TestDbProvisioner, "_set_comment"),
        ):
            status = provisioner.provision_template(
                "t", schema_hash="h", schema_sql="SELECT 1", force=True
            )

        assert status.name == "t"


class TestDropRefusal:
    def test_names_both_recognised_prefixes(self) -> None:
        provisioner = _provisioner_seeing(None)

        with pytest.raises(ConfigurationError) as exc_info:
            provisioner.drop("postgres")

        message = exc_info.value.message
        assert "not a confiture-managed" in message
        assert _TEMPLATE_PREFIX in message
        assert _CLONE_PREFIX in message

    def test_reports_a_foreign_comment_verbatim(self) -> None:
        provisioner = _provisioner_seeing("the application database")

        with pytest.raises(ConfigurationError) as exc_info:
            provisioner.drop("app")

        assert "the application database" in exc_info.value.message


class TestRamSetupRefusal:
    def test_names_the_managed_prefix(self) -> None:
        provisioner = TestDbProvisioner(_URL)
        conn = MagicMock()
        provisioner._maintenance_conn = MagicMock()  # type: ignore[method-assign]
        provisioner._maintenance_conn.return_value.__enter__.return_value = conn
        provisioner._tablespace_location = MagicMock(return_value="/dev/shm/x")  # type: ignore[method-assign]
        provisioner._dbs_in_tablespace = MagicMock(  # type: ignore[method-assign]
            return_value=[("app", None), ("other", "foreign")]
        )

        with pytest.raises(ConfigurationError) as exc_info:
            provisioner.setup_ram_tablespace(
                "ram_ts", "/dev/shm/x", owner="postgres", dir_prepared=True
            )

        message = exc_info.value.message
        assert _MANAGED_PREFIX in message
        assert "app" in message and "other" in message
