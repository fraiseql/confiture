"""Integration tests for TestDbProvisioner (P2).

Requires a reachable local PostgreSQL (CONFITURE_TEST_DB_URL or localhost).
All databases created here use the ``confiture_p2_`` prefix and are dropped in
fixture teardown.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from confiture.core.schema_artifact import build_schema_artifact
from confiture.core.temp_database import _maintenance_url
from confiture.core.test_db import TemplateState, TestDbProvisioner
from confiture.exceptions import ConfigurationError

pytestmark = pytest.mark.integration

_SCHEMA = "CREATE TABLE widget (id int PRIMARY KEY, name text);"

_TEMPLATE = "confiture_p2_template"
_CLONE = "confiture_p2_clone"


def _server_url() -> str:
    return os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")


def _drop_all(names: list[str]) -> None:
    with psycopg.connect(_maintenance_url(_server_url()), autocommit=True) as conn:
        for name in names:
            conn.execute(
                psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    psycopg.sql.Identifier(name)
                )
            )


@pytest.fixture
def provisioner() -> Iterator[TestDbProvisioner]:
    url = _server_url()
    try:
        with psycopg.connect(_maintenance_url(url), autocommit=True):
            pass
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")

    managed = [_TEMPLATE, _CLONE] + [f"{_CLONE}_{i}" for i in range(6)]
    _drop_all(managed)
    try:
        yield TestDbProvisioner(url)
    finally:
        _drop_all(managed)


def _tables(provisioner: TestDbProvisioner, db: str) -> set[str]:
    from confiture.core.temp_database import _replace_dbname

    with psycopg.connect(_replace_dbname(provisioner.server_url, db), autocommit=True) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    return {r[0] for r in rows}


class TestProvisionAndClone:
    def test_provision_template_ddl_path(self, provisioner: TestDbProvisioner) -> None:
        status = provisioner.provision_template(
            _TEMPLATE, schema_hash="hash-v1", schema_sql=_SCHEMA
        )
        assert status.state is TemplateState.CURRENT
        assert _tables(provisioner, _TEMPLATE) == {"widget"}

    def test_clone_has_template_tables(self, provisioner: TestDbProvisioner) -> None:
        provisioner.provision_template(_TEMPLATE, schema_hash="hash-v1", schema_sql=_SCHEMA)
        result = provisioner.clone(_TEMPLATE, _CLONE)
        assert result.target == _CLONE
        assert _tables(provisioner, _CLONE) == {"widget"}

    def test_provision_from_artifact(
        self, provisioner: TestDbProvisioner, tmp_path: Path
    ) -> None:
        artifact = tmp_path / "p2.full.hash.pgdump"
        build_schema_artifact(
            server_url=provisioner.server_url,
            schema_sql=_SCHEMA,
            output_path=artifact,
            schema_hash="hash-v1",
        )
        status = provisioner.provision_template(
            _TEMPLATE, schema_hash="hash-v1", from_artifact=artifact
        )
        assert status.state is TemplateState.CURRENT
        assert _tables(provisioner, _TEMPLATE) == {"widget"}


class TestStaleness:
    def test_status_current_then_stale(self, provisioner: TestDbProvisioner) -> None:
        provisioner.provision_template(_TEMPLATE, schema_hash="hash-v1", schema_sql=_SCHEMA)
        assert provisioner.template_status(_TEMPLATE, "hash-v1").state is TemplateState.CURRENT
        assert provisioner.template_status(_TEMPLATE, "hash-v2").state is TemplateState.STALE

    def test_status_absent_when_missing(self, provisioner: TestDbProvisioner) -> None:
        assert (
            provisioner.template_status(_TEMPLATE, "hash-v1").state is TemplateState.ABSENT
        )


class TestDropSafety:
    def test_drop_clone(self, provisioner: TestDbProvisioner) -> None:
        provisioner.provision_template(_TEMPLATE, schema_hash="h", schema_sql=_SCHEMA)
        provisioner.clone(_TEMPLATE, _CLONE)
        assert provisioner.drop(_CLONE) is True
        assert provisioner.template_status(_CLONE, "h").state is TemplateState.ABSENT

    def test_drop_missing_returns_false(self, provisioner: TestDbProvisioner) -> None:
        assert provisioner.drop(_CLONE) is False

    def test_drop_refuses_unmanaged_database(self, provisioner: TestDbProvisioner) -> None:
        # 'postgres' exists but is not confiture-managed → must refuse.
        with pytest.raises(ConfigurationError, match="not a confiture-managed"):
            provisioner.drop("postgres")


class TestConcurrencyAndPrune:
    def test_concurrent_clones_no_deadlock(self, provisioner: TestDbProvisioner) -> None:
        provisioner.provision_template(_TEMPLATE, schema_hash="h", schema_sql=_SCHEMA)
        errors: list[Exception] = []

        def _clone(i: int) -> None:
            try:
                provisioner.clone(_TEMPLATE, f"{_CLONE}_{i}")
            except Exception as e:  # noqa: BLE001 - recorded for assertion
                errors.append(e)

        threads = [threading.Thread(target=_clone, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, errors
        for i in range(6):
            assert _tables(provisioner, f"{_CLONE}_{i}") == {"widget"}

    def test_prune_drops_all_clones_of_template(
        self, provisioner: TestDbProvisioner
    ) -> None:
        provisioner.provision_template(_TEMPLATE, schema_hash="h", schema_sql=_SCHEMA)
        provisioner.clone(_TEMPLATE, f"{_CLONE}_0")
        provisioner.clone(_TEMPLATE, f"{_CLONE}_1")

        dropped = provisioner.prune(_TEMPLATE)

        assert set(dropped) == {f"{_CLONE}_0", f"{_CLONE}_1"}
        # Template itself survives prune.
        assert provisioner.template_status(_TEMPLATE, "h").state is TemplateState.CURRENT
