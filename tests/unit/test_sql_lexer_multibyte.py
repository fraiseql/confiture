"""Text the scanner refuses is cut at the right place, whatever alphabet precedes it.

``pglast.parser.scan`` and ``parse_sql`` report the offset of a syntax error in a
unit that is neither this text's characters nor its bytes once a multibyte
character precedes it: for ``SELECT 'ééé…'; COPY t FROM stdin;`` the index they
give is short of the truth by roughly the count of non-ASCII characters (measured
on pglast 6.16 and 8.4). COPY data is not SQL, so the scanner always errors inside
it, and the lexer cuts the text at that index to keep the tokens before it — with a
short index the cut lands before the ``COPY … FROM stdin;`` header, the block is
never recognised, and its data rows reach the parser as statements. A schema tree
holding one French seed file and one COPY block then fails to parse whole.
"""

from __future__ import annotations

import pglast
import pytest

from confiture.core.differ import SchemaDiffer
from confiture.core.parser_info import parse_error_line
from confiture.core.sql_lexer import blank_copy_blocks, code_text

#: Enough accented characters to push the reported index before the COPY header.
ACCENTED = "INSERT INTO t (label) VALUES ('" + "é" * 60 + "');\n\n"

COPY_BLOCK = (
    "COPY prep.tb_item (id, identifier) FROM stdin;\n"
    "bd1ac132-8309-4f9b-961e-bd0be0de9e2d\t<generic|1b.cabinet>\n"
    "\\.\n"
)


@pytest.mark.parametrize("prefix", ["", ACCENTED], ids=["ascii", "accented"])
def test_a_copy_block_is_blanked_whatever_precedes_it(prefix: str) -> None:
    sql = prefix + COPY_BLOCK + "SELECT 1;\n"
    blanked = blank_copy_blocks(sql)
    assert "bd1ac132" not in blanked
    assert len(blanked) == len(sql)
    assert code_text(sql).copy_blocks == 1


def test_a_schema_with_accented_text_and_a_copy_block_parses() -> None:
    sql = "CREATE TABLE t (label TEXT);\n" + ACCENTED + COPY_BLOCK
    assert [t.name for t in SchemaDiffer().parse_schema(sql).tables] == ["t"]


def test_a_syntax_error_after_accented_text_is_reported_on_its_own_line() -> None:
    sql = "SELECT '" + "é" * 60 + "';\nSELECT 1;\nSELECT 1b;\n"
    with pytest.raises(pglast.parser.ParseError) as caught:
        pglast.parse_sql(sql)
    assert parse_error_line(sql, caught.value) == 3
