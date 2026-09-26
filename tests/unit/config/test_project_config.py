"""``db/project.yaml``: the facts true in every environment of a project.

An environment file says how to reach one database; tenancy says what the schema
is, which is the same in every environment. Kept per environment, eight copies
drift, and an environment that forgot the block would silently switch the tenant
rules off there. So it lives once, in ``db/project.yaml``, and an environment file
that carries it is refused.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.config.environment import Environment
from confiture.config.project import ProjectConfig, TenancyConfig, load_project_config
from confiture.exceptions import ConfigurationError


def _write(project: Path, text: str) -> None:
    (project / "db").mkdir(parents=True, exist_ok=True)
    (project / "db" / "project.yaml").write_text(text)


def test_no_project_file_means_no_tenancy(tmp_path: Path) -> None:
    assert load_project_config(tmp_path) == ProjectConfig()
    assert load_project_config(tmp_path).tenancy is None


def test_a_tenancy_block_is_read(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tenancy:\n"
        "  discriminator: org_id\n"
        "  root: management.tb_organization\n"
        "  global_schemas: [catalog, prep_seed]\n",
    )

    tenancy = load_project_config(tmp_path).tenancy

    assert tenancy == TenancyConfig(
        discriminator="org_id",
        root="management.tb_organization",
        global_schemas=["catalog", "prep_seed"],
    )


def test_the_discriminator_defaults_to_tenant_id(tmp_path: Path) -> None:
    _write(tmp_path, "tenancy: {}\n")

    tenancy = load_project_config(tmp_path).tenancy

    assert tenancy is not None
    assert tenancy.discriminator == "tenant_id"


@pytest.mark.parametrize(
    "text",
    [
        "tenancy:\n  discriminatr: org_id\n",  # a typo is never an empty success
        "tenants: {}\n",
        "tenancy:\n  root: tb_organization\n",  # root is schema-qualified
    ],
    ids=["unknown-tenancy-key", "unknown-top-level-key", "unqualified-root"],
)
def test_a_malformed_project_file_is_refused(tmp_path: Path, text: str) -> None:
    _write(tmp_path, text)

    with pytest.raises(ConfigurationError, match=r"db/project\.yaml"):
        load_project_config(tmp_path)


def test_an_environment_file_carrying_tenancy_is_refused_and_pointed_at_the_project_file(
    tmp_path: Path,
) -> None:
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (tmp_path / "db" / "schema").mkdir()
    (env_dir / "local.yaml").write_text(
        "name: local\n"
        "database_url: postgresql://localhost/app\n"
        f"include_dirs:\n  - {tmp_path / 'db' / 'schema'}\n"
        "tenancy:\n  discriminator: tenant_id\n"
    )

    with pytest.raises(ConfigurationError, match=r"db/project\.yaml"):
        Environment.load("local", project_dir=tmp_path)
