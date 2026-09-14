"""``sql_lexer.blank_copy_blocks``: a COPY block costs its characters, not its lines.

A ``COPY … FROM stdin`` block is psql client protocol, not SQL, and pglast rejects
the whole text it appears in (#194). Deleting the block fixes the parse and moves
every line after it, which is fine for a differ that reports no positions and wrong
for a lint that reports ``file:line`` on every finding (#274).

Blanking keeps the block's newlines and replaces everything else with spaces, so a
position in the blanked text is the same position in the original — the technique
#270 established for a schema-qualified type name a compiler would not accept.
"""

from __future__ import annotations

from typing import ClassVar

import pglast.parser
import pytest

from confiture.core import sql_lexer
from confiture.core.sql_lexer import blank_copy_blocks, parse, skip_leading_comments

SQL = (
    "CREATE SCHEMA app;\n"
    "CREATE TABLE app.tb_widget (id uuid PRIMARY KEY, label text);\n"
    "COPY app.tb_widget (id, label) FROM stdin;\n"
    "0b6f1c2e-1111-4a4a-8888-000000000001\tfirst\n"
    "\\.\n"
    "CREATE TABLE app.tb_after (x int);\n"
)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


class TestBlankingPreservesOffsets:
    def test_blanking_preserves_offsets(self) -> None:
        """Same length, same lines, and the block's own characters are spaces."""
        blanked = blank_copy_blocks(SQL)

        assert len(blanked) == len(SQL)
        assert blanked.count("\n") == SQL.count("\n")
        start = SQL.index("COPY")
        end = SQL.index("\\.") + len("\\.")
        assert set(blanked[start:end]) <= {" ", "\n"}

    def test_the_statements_around_the_block_still_parse(self) -> None:
        """pglast reads the text the block used to break, before it and after it."""
        statements = pglast.parser.parse_sql(blank_copy_blocks(SQL))

        assert [type(raw.stmt).__name__ for raw in statements] == [
            "CreateSchemaStmt",
            "CreateStmt",
            "CreateStmt",
        ]

    def test_a_location_still_indexes_the_original_text(self) -> None:
        """A position found in the blanked text is that position in the original.

        Read through ``sql_lexer.parse``, not off ``stmt_location`` directly:
        before PostgreSQL 18 a statement's location included the whitespace
        before it, so on pglast 6 and 7 the raw offset here is the newline after
        the previous ``;`` and every blanked character after it. That is the
        difference the lexer's ``skip_leading_comments`` exists to absorb, and
        absorbing it is the only portable way to ask this question.
        """
        statements = parse(blank_copy_blocks(SQL))

        last = statements[-1]
        start = skip_leading_comments(blank_copy_blocks(SQL), last.location)
        assert SQL[start:].startswith("CREATE TABLE app.tb_after")
        assert last.line == _line_of(SQL, SQL.index("CREATE TABLE app.tb_after"))

    def test_the_raw_text_does_not_parse(self) -> None:
        """The premise: without blanking there is nothing to read at all."""
        with pytest.raises(pglast.parser.ParseError):
            pglast.parser.parse_sql(SQL)


class TestBlankingIsNotStripping:
    def test_text_without_a_block_is_unchanged(self) -> None:
        sql = "COPY t FROM '/path';\n-- COPY x FROM stdin\nSELECT 1;\n"
        assert blank_copy_blocks(sql) == sql

    def test_two_blocks_are_both_blanked(self) -> None:
        sql = (
            "COPY t (a) FROM stdin;\n1\n\\.\n"
            "CREATE TABLE u (b int);\n"
            "COPY u (b) FROM stdin;\n2\n\\.\n"
        )
        blanked = blank_copy_blocks(sql)

        assert len(blanked) == len(sql)
        assert blanked.count("\n") == sql.count("\n")
        assert [type(raw.stmt).__name__ for raw in pglast.parser.parse_sql(blanked)] == [
            "CreateStmt"
        ]

    def test_an_unterminated_block_runs_to_the_end(self) -> None:
        """No ``\\.``: the rest of the text is data, and blanking says so without hanging."""
        sql = "CREATE TABLE t (a int);\nCOPY t (a) FROM stdin;\n1\n2\n"
        blanked = blank_copy_blocks(sql)

        assert len(blanked) == len(sql)
        assert blanked.startswith("CREATE TABLE t (a int);\n")
        assert blanked[sql.index("COPY") :].strip() == ""

    def test_a_dollar_quoted_terminator_is_not_a_terminator(self) -> None:
        r"""A ``\.`` inside a routine body is body text, so the lexer never sees a block."""
        sql = "CREATE FUNCTION f() RETURNS text AS $$ SELECT '\\.' $$ LANGUAGE sql;\n"
        assert blank_copy_blocks(sql) == sql


class TestOneCopyBlockFunction:
    """The lexer answers "where are the COPY blocks" once, and blanking is the answer.

    ``strip_copy_blocks`` was the first answer (#194) and its only caller was
    ``core/differ.py``, which parses and then regex-scans. Blanking serves that
    caller unchanged *and* keeps a ``DIFFER_400`` position pointing at the real
    file, so keeping both would be two answers to one question — the standing
    rule ``test_one_sql_lexer.py`` exists to hold.
    """

    def test_the_lexer_exposes_no_stripping_variant(self) -> None:
        assert not hasattr(sql_lexer, "strip_copy_blocks")

    def test_the_stripped_fixture_is_blanked_in_place(self) -> None:
        """The case ``strip_copy_blocks`` used to shorten, kept at full length."""
        sql = (
            "CREATE TABLE t (a int);\nCOPY t (a) FROM stdin;\n1\n'\n\\.\nCREATE TABLE u (b int);\n"
        )

        blanked = blank_copy_blocks(sql)

        assert blanked == (
            "CREATE TABLE t (a int);\n                      \n \n \n  \nCREATE TABLE u (b int);\n"
        )


class TestScanWindowIsInvisible:
    r"""The window ``_lex`` scans ahead in changes how much is read, never what is read.

    Before #278 the rescan after each block handed ``pglast.parser.scan`` the whole
    rest of the file, so n blocks cost O(n x total) — 8000 blocks took 15.6 s. The
    rescan now grows a window until the next ``COPY … FROM stdin;`` is inside it.

    A window larger than the input takes the whole-remainder branch, which is the
    pre-#278 algorithm exactly; a window of one byte forces the growth loop to its
    limit. Every public answer has to be the same at both ends and everywhere
    between, on inputs built to break a prefix scan: a block at offset zero, a block
    that never terminates, `COPY … FROM stdin;` spelled inside a comment, a string
    and a dollar-quoted body, and a gap between two blocks far wider than the
    starting window.
    """

    _WINDOWS = (1, 7, 64, 512, 1 << 20)

    CORPUS: ClassVar[dict[str, str]] = {
        "empty": "",
        "no_copy": "CREATE TABLE t (a int);\nSELECT 1;\n",
        "block_at_offset_zero": "COPY t (a) FROM stdin;\n1\n2\n\\.\nSELECT 1;\n",
        "block_at_eof_no_terminator": "SELECT 1;\nCOPY t (a) FROM stdin;\n1\n2\n",
        "terminator_without_trailing_newline": "COPY t (a) FROM stdin;\n1\n\\.",
        "two_blocks": "COPY a (x) FROM stdin;\n1\n\\.\nCOPY b (y) FROM stdin;\n2\n\\.\nSELECT 1;\n",
        "copy_inside_block_comment": "/* COPY t (a) FROM stdin;\n1\n\\. */\nSELECT 1;\n",
        "copy_inside_string": "SELECT 'COPY t (a) FROM stdin;\n1\n\\.\n';\nSELECT 2;\n",
        "copy_inside_dollar_quote": "DO $$ BEGIN RAISE NOTICE 'COPY t FROM stdin;'; END $$;\nSELECT 1;\n",
        "crlf": "COPY t (a) FROM stdin;\r\n1\r\n\\.\r\nSELECT 1;\r\n",
        "trailing_comment_on_the_copy_line": "COPY t (a) FROM stdin; -- go\n1\n\\.\nSELECT 1;\n",
        "directive_after_a_block": "COPY t (a) FROM stdin;\n1\n\\.\n-- confiture:destructive\nDROP TABLE t;\n",
        "data_holding_semicolons_and_quotes": "COPY t (a) FROM stdin;\na;b\t'unclosed\n\\.\nSELECT 1;\n",
        "copy_not_from_stdin": "COPY t (a) FROM '/tmp/f.csv';\nSELECT 1;\n",
        "unparseable_before_a_block": "CREATE ROLE IF NOT EXISTS x;\nCOPY t (a) FROM stdin;\n1\n\\.\nSELECT 1;\n",
        "unterminated_string_after_a_block": "COPY t (a) FROM stdin;\n1\n\\.\nSELECT 'oops;\n",
        "dollar_quote_between_blocks": (
            "COPY a (x) FROM stdin;\n1\n\\.\n"
            "DO $t$ SELECT 'COPY b FROM stdin;' $t$;\n"
            "COPY b (y) FROM stdin;\n2\n\\.\n"
        ),
        "gap_far_wider_than_the_starting_window": (
            "COPY a (x) FROM stdin;\n1\n\\.\n/* "
            + "y" * 4000
            + " */\nCOPY b (y) FROM stdin;\n2\n\\.\n"
        ),
        # The scanner reads `\.` without complaint, so a block whose data lexes cleanly
        # leaves the original token list in sync and no rescan happens at all. An
        # apostrophe in a value — ubiquitous in a real dump — is what makes the scanner
        # error inside the data, truncate, and send `_lex` down the rescan path this
        # class exists to cover.
        "quoted_data_forces_a_rescan": ("COPY t (a, b) FROM stdin;\n1\tO'Brien\n\\.\nSELECT 1;\n"),
        "quoted_data_then_another_block": (
            "COPY a (x) FROM stdin;\n1\tO'Brien\n\\.\n"
            "CREATE TABLE mid (z int);\n"
            "COPY b (y) FROM stdin;\n2\tD'Arcy\n\\.\nSELECT 1;\n"
        ),
        "quoted_data_with_a_wide_gap_between_blocks": (
            "COPY a (x) FROM stdin;\n1\tO'Brien\n\\.\n"
            "-- " + "q" * 3000 + "\n"
            "COPY b (y) FROM stdin;\n2\tD'Arcy\n\\.\nSELECT 1;\n"
        ),
        # A clean block reached *through* a rescan: the quoted first block sends `_lex`
        # down the windowed path, and the second block's data lexes fine, so the window
        # can overshoot `data_end` and look in sync there. Trusting it drops every token
        # past the window — 59 of 76 here — and leaves the block offsets looking right.
        "clean_block_reached_through_a_rescan": (
            "COPY a (x) FROM stdin;\n1\tO'Brien\n\\.\n"
            "COPY b (y) FROM stdin;\n1\n\\.\n" + "SELECT 1;\n" * 20
        ),
        "many_quoted_blocks": "".join(
            f"CREATE TABLE q{i} (a int, b text);\nCOPY q{i} (a, b) FROM stdin;\n{i}\tO'Brien\n\\.\n"
            for i in range(25)
        ),
        "many_blocks": "".join(
            f"CREATE TABLE t{i} (a int);\nCOPY t{i} (a) FROM stdin;\n{i}\n\\.\n" for i in range(40)
        ),
    }

    @staticmethod
    def _answers(sql: str) -> dict:
        def call(fn, *args):
            try:
                return ("ok", fn(*args))
            except Exception as exc:  # the error is an answer too
                return ("raise", type(exc).__name__, str(exc))

        text = sql_lexer.code_text(sql)
        return {
            "tokens": call(lambda s: [(t.name, t.start, t.end) for t in sql_lexer.tokens(s)], sql),
            "blocks": call(lambda s: sql_lexer._lex(s)[1], sql),
            "split_statements": call(sql_lexer.split_statements, sql),
            "strip_comments": call(sql_lexer.strip_comments, sql),
            "blank_copy_blocks": call(blank_copy_blocks, sql),
            "code_text": (text.text, text.copy_blocks),
            "comments": call(
                lambda s: [(c.text, c.line, c.kind) for c in sql_lexer.comments(s)], sql
            ),
            "directives": call(lambda s: [(d.name, d.line) for d in sql_lexer.directives(s)], sql),
        }

    @pytest.mark.parametrize("name", sorted(CORPUS))
    def test_every_window_gives_the_same_answer(self, name: str, monkeypatch) -> None:
        sql = self.CORPUS[name]
        monkeypatch.setattr(sql_lexer, "_SCAN_WINDOW", self._WINDOWS[-1])
        whole_remainder = self._answers(sql)
        for window in self._WINDOWS[:-1]:
            monkeypatch.setattr(sql_lexer, "_SCAN_WINDOW", window)
            assert self._answers(sql) == whole_remainder, (
                f"a {window}-byte scan window changed the answer for {name!r}; it may only "
                "change how much text is read"
            )

    def test_the_corpus_reaches_the_code_it_guards(self, monkeypatch) -> None:
        """Holding COPY blocks is not enough, and assuming it was is how this started.

        A block whose rows lex cleanly leaves the scan in sync, resumes, and never
        calls ``_scan_after_block`` at all — so a corpus of those exercises the window
        nowhere while looking thorough. Count the entries that actually rescan.
        """
        real = sql_lexer._scan_after_block
        current: dict[str, str] = {}
        rescanned: set[str] = set()

        def counting(sql: str, start: int):
            rescanned.add(current["name"])
            return real(sql, start)

        monkeypatch.setattr(sql_lexer, "_scan_after_block", counting)
        with_blocks = set()
        for name, sql in self.CORPUS.items():
            current["name"] = name
            if sql_lexer._lex(sql)[1]:
                with_blocks.add(name)
        assert len(with_blocks) >= 15, sorted(with_blocks)
        assert len(rescanned) >= 4, sorted(rescanned)


class TestTheTextIsScannedOnce:
    r"""How much text ``_lex`` hands the scanner does not grow with the block count.

    The wall-clock half of #278 is on the benchmark leg
    (``tests/performance/test_lexer_scaling``); this is the half that needs no clock.
    ``pglast.parser.scan`` reads its whole buffer however early its error is, so
    before the fix every block rescanned the rest of the file and the text handed to
    the scanner grew with the square of the block count — 38x the file at 50 blocks,
    151x at 200, 602x at 800. It is now flat, and flat is the assertion.

    The data values carry an apostrophe on purpose. ``\.`` scans without complaint
    (``ASCII_92``, ``ASCII_46``), so a block whose rows lex cleanly leaves the
    original token list in sync and never reaches the rescan at all; an unterminated
    quote inside the data is what sends it there, and it is in every real dump.
    """

    # Measured 3.1x-4.6x depending on how far apart the blocks sit. Every window from
    # 32 to 1024 bytes clears this, so the bound does not pin the one that was chosen;
    # 4096 does not (55x), and neither does a quadratic at any size.
    _MAX_SCANNED = 15

    @staticmethod
    def _seed_sql(blocks: int, rows: int = 3) -> str:
        return "".join(
            f"CREATE TABLE t{i} (a int, b text);\nCOPY t{i} (a, b) FROM stdin;\n"
            + "".join(f"{r}\tO'Brien-{r}\n" for r in range(rows))
            + "\\.\n"
            for i in range(blocks)
        )

    def _scanned_per_byte(self, sql: str, expected_blocks: int, monkeypatch) -> float:
        scanned = 0
        real_scan = pglast.parser.scan

        def counting(text: str):
            nonlocal scanned
            scanned += len(text)
            return real_scan(text)

        monkeypatch.setattr(pglast.parser, "scan", counting)
        _tokens, blocks = sql_lexer._lex(sql)
        assert len(blocks) == expected_blocks, f"found {len(blocks)} of {expected_blocks}"
        return scanned / len(sql)

    @pytest.mark.parametrize("blocks", [50, 200, 800])
    def test_scanned_text_stays_proportional_to_the_file(self, blocks: int, monkeypatch) -> None:
        ratio = self._scanned_per_byte(self._seed_sql(blocks), blocks, monkeypatch)
        assert ratio < self._MAX_SCANNED, (
            f"{blocks} blocks handed the scanner {ratio:.1f}x the file; the rescan after a "
            "block is reading past the next one (#278)"
        )

    def test_the_corpus_really_does_defeat_the_scanner(self, monkeypatch) -> None:
        """Without the apostrophe the rescan never runs and the bound above is vacuous."""
        clean = self._seed_sql(50).replace("O'Brien", "plain")
        assert self._scanned_per_byte(clean, 50, monkeypatch) < 1.5, "clean data should resume"
        assert self._scanned_per_byte(self._seed_sql(50), 50, monkeypatch) > 1.5, (
            "quoted data must force the rescan this class is about"
        )
