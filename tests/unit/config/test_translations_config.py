"""``db/project.yaml``'s ``translations:`` block: which tables translate what (#657).

A translation table is a fact about the schema, the same in every environment, so
it is declared beside ``soft_delete:``, and an environment file carrying it is
refused as one carrying ``soft_delete:`` is.
"""

from pathlib import Path

import pytest

from confiture.config.environment import Environment
from confiture.config.project import TranslationsConfig, load_project_config
from confiture.exceptions import ConfigurationError


def _write(project: Path, text: str) -> None:
    (project / "db").mkdir(parents=True, exist_ok=True)
    (project / "db" / "project.yaml").write_text(text)


def test_the_block_is_read_with_its_defaults(tmp_path: Path) -> None:
    _write(tmp_path, "translations:\n  tables: 'tl_*'\n  locale_table: public.tb_locale\n")

    config = load_project_config(tmp_path)

    assert config.translations == TranslationsConfig(
        tables=["tl_*"], locale_table="public.tb_locale"
    )
    assert config.translations.locale_fk == "fk_locale"
    assert config.translations.locale_column == "code"
    assert config.declared_blocks() == frozenset({"translations"})


def test_tables_may_be_a_list_and_locales_required(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "translations:\n"
        "  tables: [catalog.tl_*, tl_country]\n"
        "  locale_table: tb_locale\n"
        "  locale_fk: fk_language\n"
        "  locale_column: iso\n"
        "  required: [en-US, fr-FR]\n",
    )

    config = load_project_config(tmp_path).translations

    assert config is not None
    assert config.tables == ["catalog.tl_*", "tl_country"]
    assert (config.locale_fk, config.locale_column) == ("fk_language", "iso")
    assert config.required == ["en-US", "fr-FR"]


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        ("translations:\n  locale_table: tb_locale\n", "tables"),
        ("translations:\n  tables: 'tl_*'\n", "locale_table"),
        ("translations:\n  tables: []\n  locale_table: tb_locale\n", "tables"),
        ("translations:\n  tables: 'tl_*'\n  locale_table: a.b.c\n", "locale_table"),
        (
            "translations:\n  tables: 'tl_*'\n  locale_table: tb_locale\n"
            "  required: [en-US]\n  required_query: SELECT 'en-US'\n",
            "required_query",
        ),
        ("translations:\n  tables: 'tl_*'\n  locale_table: tb_locale\n  typo: 1\n", "typo"),
    ],
)
def test_a_malformed_block_is_refused(tmp_path: Path, text: str, complaint: str) -> None:
    _write(tmp_path, text)

    with pytest.raises(ConfigurationError, match=complaint):
        load_project_config(tmp_path)


def test_an_environment_file_refuses_the_block(tmp_path: Path) -> None:
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (tmp_path / "db" / "schema").mkdir()
    (env_dir / "local.yaml").write_text(
        "name: local\n"
        "database_url: postgresql://localhost/app\n"
        f"include_dirs:\n  - {tmp_path / 'db' / 'schema'}\n"
        "translations:\n  tables: 'tl_*'\n  locale_table: tb_locale\n"
    )

    with pytest.raises(ConfigurationError, match=r"'translations' is a fact about the schema"):
        Environment.load("local", project_dir=tmp_path)
