"""Which entity rows have no translation in a required locale, counted live (#657)."""

import psycopg
import pytest

from confiture.config.project import ProjectConfig, SoftDeleteConfig, TranslationsConfig
from confiture.core.sql_lexer import parse_file
from confiture.core.translations import translation_coverage

DDL = """
CREATE TABLE tb_locale (pk_locale bigint PRIMARY KEY, code text NOT NULL UNIQUE);
CREATE TABLE tb_category (pk_category bigint PRIMARY KEY, deleted_at timestamptz);
CREATE TABLE tl_category (
    pk_tl_category bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fk_category bigint NOT NULL REFERENCES tb_category,
    fk_locale bigint NOT NULL REFERENCES tb_locale,
    label text NOT NULL,
    deleted_at timestamptz
);
CREATE UNIQUE INDEX uq_tl_category ON tl_category (fk_category, fk_locale)
    WHERE deleted_at IS NULL;
"""

DATA = """
INSERT INTO tb_locale VALUES (1, 'en-US'), (2, 'fr-FR');
INSERT INTO tb_category VALUES (1, NULL), (2, NULL), (3, NULL), (4, NULL), (5, NULL), (6, now());
INSERT INTO tl_category (fk_category, fk_locale, label, deleted_at)
SELECT c, 1, 'en', NULL FROM generate_series(1, 5) c
UNION ALL VALUES (1, 2, 'fr', NULL), (2, 2, 'fr', NULL), (3, 2, 'fr', now());
"""


def _project(**translations: object) -> ProjectConfig:
    return ProjectConfig(
        soft_delete=SoftDeleteConfig(),
        translations=TranslationsConfig(tables=["tl_*"], locale_table="tb_locale", **translations),
    )


@pytest.fixture
def filled(clean_test_db: psycopg.Connection) -> psycopg.Connection:
    with clean_test_db.cursor() as cur:
        cur.execute(DDL)
        cur.execute(DATA)
    clean_test_db.commit()
    return clean_test_db


def _gaps(
    conn: psycopg.Connection, project: ProjectConfig
) -> dict[str, tuple[int, tuple[str, ...]]]:
    coverage = translation_coverage(conn, [parse_file(DDL, "010.sql", 0)], project)
    ((table, gaps),) = [(t.table, t.gaps) for t in coverage.tables]
    assert table == "tl_category"
    return {gap.locale: (gap.missing, gap.sample) for gap in gaps}


def test_each_required_locale_counts_the_live_entities_it_misses(
    filled: psycopg.Connection,
) -> None:
    gaps = _gaps(filled, _project(required=["en-US", "fr-FR"]))

    # Category 6 is deleted; category 3's French label is too.
    assert gaps == {"en-US": (0, ()), "fr-FR": (3, ("3", "4", "5"))}


def test_the_sample_is_the_first_keys(filled: psycopg.Connection) -> None:
    coverage = translation_coverage(
        filled, [parse_file(DDL, "010.sql", 0)], _project(required=["fr-FR"]), sample=2
    )
    assert coverage.tables[0].gaps[0].sample == ("3", "4")
    assert coverage.missing == 3


def test_a_locale_the_locale_table_lacks_is_named_and_misses_everything(
    filled: psycopg.Connection,
) -> None:
    coverage = translation_coverage(
        filled, [parse_file(DDL, "010.sql", 0)], _project(required=["de-DE"])
    )
    assert coverage.unknown_locales == ("de-DE",)
    assert coverage.tables[0].gaps[0].missing == 5


def test_the_required_locales_may_come_from_a_query(filled: psycopg.Connection) -> None:
    gaps = _gaps(
        filled, _project(required_query="SELECT code FROM tb_locale WHERE code LIKE 'fr%'")
    )
    assert gaps == {"fr-FR": (3, ("3", "4", "5"))}


def test_a_table_i18n_001_refuses_is_not_counted(filled: psycopg.Connection) -> None:
    ddl = DDL.replace("CREATE UNIQUE INDEX uq_tl_category", "CREATE INDEX ix_tl_category")
    coverage = translation_coverage(
        filled, [parse_file(ddl, "010.sql", 0)], _project(required=["fr-FR"])
    )
    assert coverage.tables == ()
    assert len(coverage.not_counted) == 1
    assert coverage.not_counted[0].startswith("tl_category holds more than one row")
