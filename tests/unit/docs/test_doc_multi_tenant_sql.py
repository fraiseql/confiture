"""Every SQL block of the multi-tenant guide is PostgreSQL.

The guide teaches a schema shape by example, and a reader copies the examples. A
block PostgreSQL's own parser rejects teaches nothing, so each ```sql fence is
parsed with pglast — whole statements only, never a clause on its own.
"""

from __future__ import annotations

import pglast
import pytest
from doc_snippets import all_fenced, read_doc

GUIDE = "docs/guides/multi-tenant-schemas.md"
BLOCKS = all_fenced(read_doc(GUIDE), "sql")


def test_the_guide_teaches_by_sql() -> None:
    assert len(BLOCKS) >= 10, "the guide lost its SQL examples"


@pytest.mark.parametrize("block", BLOCKS, ids=[f"block-{i}" for i in range(len(BLOCKS))])
def test_each_sql_block_parses(block: str) -> None:
    assert pglast.parse_sql(block), "an SQL block holds no statement"
