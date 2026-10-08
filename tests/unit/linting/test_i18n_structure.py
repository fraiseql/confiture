"""``i18n_001``: a translation table has the shape a coverage check can count (#657).

Each table ``translations.tables`` names references the locale table through
``locale_fk``, references exactly one translated entity, and holds one row per
entity and locale — among live rows when it soft-deletes.
"""

import pytest

from confiture.config.project import SoftDeleteConfig, TranslationsConfig
from confiture.core.linting.inventory import build_inventory
from confiture.core.linting.soft_delete import soft_deleting
from confiture.core.linting.translations import translation_findings
from confiture.core.sql_lexer import parse_file

_LOCALE = (
    "CREATE TABLE tb_locale (pk_locale bigint PRIMARY KEY, code text UNIQUE);\n"
    "CREATE TABLE tb_category (pk_category bigint PRIMARY KEY);\n"
)
_GOOD = (
    "CREATE TABLE tl_category (\n"
    "  pk_tl_category bigint PRIMARY KEY,\n"
    "  fk_category bigint NOT NULL REFERENCES tb_category,\n"
    "  fk_locale bigint NOT NULL REFERENCES tb_locale,\n"
    "  fk_created_by bigint REFERENCES tb_category,\n"
    "  label text,\n"
    "  UNIQUE (fk_category, fk_locale)\n"
    ");\n"
)
_CONFIG = TranslationsConfig(tables=["tl_*"], locale_table="tb_locale")


def _messages(sql: str, config: TranslationsConfig = _CONFIG, soft: bool = False) -> list[str]:
    files = [parse_file(sql, "010.sql", 0)]
    inventory = build_inventory(files)
    deleting = (
        soft_deleting(inventory, files, SoftDeleteConfig(column="deleted_at")) if soft else None
    )
    return [f.message for f in translation_findings(inventory, files, config, deleting)]


def test_a_well_formed_table_is_no_finding() -> None:
    assert _messages(_LOCALE + _GOOD) == []


def test_a_table_without_the_locale_column() -> None:
    sql = _LOCALE + _GOOD.replace("fk_locale bigint NOT NULL REFERENCES tb_locale,\n", "")
    sql = sql.replace("UNIQUE (fk_category, fk_locale)", "UNIQUE (fk_category)")
    assert _messages(sql) == ["tl_category has no column fk_locale"]


def test_a_locale_column_that_references_nothing() -> None:
    sql = _LOCALE + _GOOD.replace(
        "fk_locale bigint NOT NULL REFERENCES tb_locale", "fk_locale bigint"
    )
    assert _messages(sql) == ["tl_category.fk_locale does not reference tb_locale"]


def test_no_unique_key_over_the_entity_and_the_locale() -> None:
    sql = _LOCALE + _GOOD.replace(",\n  UNIQUE (fk_category, fk_locale)", "")
    (message,) = _messages(sql)
    assert message == (
        "tl_category holds more than one row per entity and locale: no foreign key "
        "forms a unique key with fk_locale (UNIQUE (fk_category, fk_locale), the one "
        "referencing tb_category?)"
    )


def test_two_entities_in_one_table() -> None:
    sql = _LOCALE + _GOOD.replace(
        "UNIQUE (fk_category, fk_locale)",
        "UNIQUE (fk_category, fk_locale),\n  UNIQUE (fk_created_by, fk_locale)",
    )
    (message,) = _messages(sql)
    assert message.startswith("tl_category translates more than one entity")


def test_a_soft_deleting_table_needs_the_key_among_live_rows() -> None:
    soft = _GOOD.replace("label text,", "label text,\n  deleted_at timestamptz,")
    (message,) = _messages(_LOCALE + soft, soft=True)
    assert "among live rows" in message
    live = soft.replace(",\n  UNIQUE (fk_category, fk_locale)", "") + (
        "CREATE UNIQUE INDEX uq_tl ON tl_category (fk_category, fk_locale) "
        "WHERE deleted_at IS NULL;\n"
    )
    assert _messages(_LOCALE + live, soft=True) == []


def test_an_entity_the_tree_does_not_create() -> None:
    sql = _LOCALE.replace("CREATE TABLE tb_category (pk_category bigint PRIMARY KEY);\n", "")
    sql += _GOOD.replace("  fk_created_by bigint REFERENCES tb_category,\n", "")
    assert _messages(sql) == [
        "tl_category.fk_category references tb_category, which the tree does not create"
    ]


def test_a_glob_that_matches_no_table() -> None:
    config = TranslationsConfig(tables=["tl_*", "catalog.tl_*"], locale_table="tb_locale")
    assert _messages(_LOCALE + _GOOD, config) == [
        "translations.tables 'catalog.tl_*' matches no table"
    ]


def test_a_locale_table_the_tree_does_not_create() -> None:
    config = TranslationsConfig(tables=["tl_*"], locale_table="i18n.tb_locale")
    assert "translations.locale_table i18n.tb_locale is not a table the tree creates" in (
        _messages(_LOCALE + _GOOD, config)
    )


@pytest.mark.parametrize(
    ("glob", "matches"),
    [("tl_*", True), ("public.tl_*", True), ("catalog.tl_*", False), ("TL_Category", True)],
)
def test_a_glob_reads_a_dotted_pattern_as_schema_and_name(glob: str, matches: bool) -> None:
    config = TranslationsConfig(tables=[glob], locale_table="tb_locale")
    messages = _messages(_LOCALE + _GOOD, config)
    assert (messages == []) is matches
