"""``db/project.yaml``'s ``soft_delete:`` block: which column marks a row deleted.

A table that has the tombstone column soft-deletes, and that is a fact about the
schema, the same in every environment — so it is declared beside ``tenancy:``, and
an environment file that carries it is refused as one carrying ``tenancy:`` is.
"""

from pathlib import Path

import pytest

from confiture.config.environment import Environment
from confiture.config.project import ProjectConfig, SoftDeleteConfig, load_project_config
from confiture.exceptions import ConfigurationError


def _write(project: Path, text: str) -> None:
    (project / "db").mkdir(parents=True, exist_ok=True)
    (project / "db" / "project.yaml").write_text(text)


def test_no_block_declares_no_soft_delete(tmp_path: Path) -> None:
    _write(tmp_path, "tenancy: {}\n")

    config = load_project_config(tmp_path)

    assert config.soft_delete is None
    assert "soft_delete" not in config.declared_blocks()


@pytest.mark.parametrize("text", ["soft_delete:\n", "soft_delete: {}\n"])
def test_an_empty_block_declares_the_default_column(tmp_path: Path, text: str) -> None:
    _write(tmp_path, text)

    config = load_project_config(tmp_path)

    assert config.soft_delete == SoftDeleteConfig(column="deleted_at")
    assert config.declared_blocks() == frozenset({"soft_delete"})


def test_the_column_is_read(tmp_path: Path) -> None:
    _write(tmp_path, "soft_delete:\n  column: removed_at\n")

    assert load_project_config(tmp_path) == ProjectConfig(
        soft_delete=SoftDeleteConfig(column="removed_at")
    )


@pytest.mark.parametrize(
    "text",
    [
        "soft_delete:\n  column: ''\n",
        "soft_delete:\n  column: '  '\n",
        "soft_delete:\n  colum: removed_at\n",
    ],
    ids=["empty-column", "blank-column", "unknown-key"],
)
def test_a_malformed_block_is_refused(tmp_path: Path, text: str) -> None:
    _write(tmp_path, text)

    with pytest.raises(ConfigurationError, match=r"db/project\.yaml") as refused:
        load_project_config(tmp_path)

    assert refused.value.error_code == "CONFIG_001"


def test_an_environment_file_carrying_soft_delete_is_refused_like_tenancy(
    tmp_path: Path,
) -> None:
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (tmp_path / "db" / "schema").mkdir()
    (env_dir / "local.yaml").write_text(
        "name: local\n"
        "database_url: postgresql://localhost/app\n"
        f"include_dirs:\n  - {tmp_path / 'db' / 'schema'}\n"
        "soft_delete:\n  column: deleted_at\n"
    )

    with pytest.raises(ConfigurationError, match=r"db/project\.yaml") as refused:
        Environment.load("local", project_dir=tmp_path)

    assert refused.value.error_code == "CONFIG_010"


def test_tables_defaults_to_present_and_reads_written(tmp_path: Path) -> None:
    """#640: ``present`` keeps 1.30's meaning; ``written`` is asked for."""
    assert SoftDeleteConfig().tables == "present"
    _write(tmp_path, "soft_delete:\n  tables: written\n  exclude: [app.tb_x, tb_y]\n")
    config = load_project_config(tmp_path).soft_delete
    assert config is not None
    assert config.tables == "written"
    assert config.exclude == ["app.tb_x", "tb_y"]


@pytest.mark.parametrize(
    "text",
    [
        "soft_delete:\n  tables: all\n",
        "soft_delete:\n  exclude: ['a.b.c']\n",
        "soft_delete:\n  exclude: ['']\n",
    ],
)
def test_a_tables_mode_or_exclude_entry_it_cannot_read_is_refused(
    tmp_path: Path, text: str
) -> None:
    _write(tmp_path, text)
    with pytest.raises(ConfigurationError):
        load_project_config(tmp_path)
