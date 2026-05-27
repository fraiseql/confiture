"""#132: ``BEGIN`` and ``COMMIT`` inside ``DO $$ ... $$`` blocks must NOT be stripped.

The historic line-by-line regex stripper mistook PL/pgSQL ``BEGIN``/``COMMIT``
keywords inside dollar-quoted blocks for transaction wrappers and deleted
them, breaking a standard PostgreSQL idiom. The scanner-driven stripper
preserves dollar-quote contents verbatim.
"""

import re

from confiture.core.sql_utils import strip_transaction_wrappers


class TestDoBlockPreservation:
    def test_do_block_with_begin_end_preserved(self):
        sql = (
            "CREATE TABLE thingies (id BIGSERIAL PRIMARY KEY, tag TEXT);\n"
            "DO $$\n"
            "BEGIN\n"
            "    INSERT INTO thingies (tag) VALUES ('initial');\n"
            "EXCEPTION\n"
            "    WHEN OTHERS THEN\n"
            "        INSERT INTO thingies (tag) VALUES ('fallback');\n"
            "END $$;\n"
        )
        result, changed = strip_transaction_wrappers(sql, return_changed=True)
        assert "BEGIN" in result, "PL/pgSQL BEGIN must be preserved inside DO block"
        assert "END $$;" in result
        assert changed is False, "no top-level BEGIN/COMMIT to strip"

    def test_do_block_with_tag_preserved(self):
        sql = (
            "CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql AS $body$\n"
            "BEGIN\n"
            "    INSERT INTO t VALUES (1);\n"
            "END\n"
            "$body$;\n"
        )
        result = strip_transaction_wrappers(sql)
        assert "BEGIN" in result
        assert "END" in result

    def test_top_level_begin_still_stripped(self):
        sql = "BEGIN;\nCREATE TABLE t (id INT);\nCOMMIT;\n"
        result, changed = strip_transaction_wrappers(sql, return_changed=True)
        assert "BEGIN" not in result
        assert "COMMIT" not in result
        assert "CREATE TABLE" in result
        assert changed is True

    def test_top_level_and_do_block_mixed(self):
        sql = "BEGIN;\nDO $$\nBEGIN\n    INSERT INTO t VALUES (1);\nEND $$;\nCOMMIT;\n"
        result, changed = strip_transaction_wrappers(sql, return_changed=True)
        # The leading top-level BEGIN; and trailing top-level COMMIT; must be gone.
        # We can't simply grep for "BEGIN" because the DO block has its own
        # PL/pgSQL BEGIN keyword that must survive — instead check that the
        # ``BEGIN;`` / ``COMMIT;`` standalone variants (with semicolon) no
        # longer appear, and that the DO block survives intact.
        assert "BEGIN;" not in result, f"top-level BEGIN; not stripped:\n{result}"
        assert "COMMIT;" not in result, f"top-level COMMIT; not stripped:\n{result}"
        assert "DO $$" in result
        assert "END $$;" in result
        # The inner BEGIN of the DO block must still be present —
        # match the indented form that's inside the dollar-quoted block.
        assert re.search(r"DO \$\$\s*\n\s*BEGIN", result) is not None, (
            f"inner BEGIN of DO block was stripped:\n{result}"
        )
        assert changed is True

    def test_commit_inside_string_preserved(self):
        """A literal ``COMMIT`` token inside a multi-line string must survive."""
        sql = "INSERT INTO log (note) VALUES ('this is\nCOMMIT\nnot a wrapper');\n"
        result, changed = strip_transaction_wrappers(sql, return_changed=True)
        assert "COMMIT" in result, "COMMIT inside string must be preserved"
        assert changed is False

    def test_crlf_line_endings_top_level_begin_stripped(self):
        """Top-level wrappers must still be stripped with CRLF line endings."""
        sql = "BEGIN;\r\nCREATE TABLE t (id INT);\r\nCOMMIT;\r\n"
        result, changed = strip_transaction_wrappers(sql, return_changed=True)
        assert "BEGIN" not in result
        assert "COMMIT" not in result
        assert "CREATE TABLE" in result
        assert changed is True
