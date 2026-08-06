"""Split a SQL script into top-level statements.

Shared by the two statement walkers — ``core/change_set.py`` (risk tiers, #197)
and ``core/replica/classifier.py`` (the ``window_safe`` verdict, #154). Both
previously carried their own splitter, and the replica one was a bare
``sql.split(";")`` that shredded a dollar-quoted function body into fragments.
That was invisible while unrecognised fragments were silently dropped; once they
became ``Other`` (#206) each fragment would have raised a spurious
``PFLIGHT_REPLICA_UNCLASSIFIED`` finding.

The splitter is deliberately lexical rather than a parser: it runs on the regex
fallback path, where pglast is unavailable by definition.
"""

from __future__ import annotations

import re

__all__ = ["split_statements"]

_DOLLAR_TAG = re.compile(r"\$(?:[A-Za-z_]\w*)?\$")


def split_statements(sql: str) -> list[str]:
    """Split on top-level ``;``, respecting dollar-quoted bodies, literals and comments.

    Returns the non-empty statements, stripped. A trailing ``;`` yields no empty
    final element.
    """
    statements: list[str] = []
    buf: list[str] = []
    index = 0
    length = len(sql)
    tag: str | None = None

    while index < length:
        char = sql[index]
        if tag is not None:
            if sql.startswith(tag, index):
                buf.append(tag)
                index += len(tag)
                tag = None
            else:
                buf.append(char)
                index += 1
            continue
        if char == "$":
            opener = _DOLLAR_TAG.match(sql, index)
            if opener:
                tag = opener.group(0)
                buf.append(tag)
                index += len(tag)
                continue
        if char == "'":
            end = index + 1
            while end < length:
                if sql[end] == "'":
                    if end + 1 < length and sql[end + 1] == "'":
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            buf.append(sql[index:end])
            index = end
            continue
        if sql.startswith("--", index):
            newline = sql.find("\n", index)
            index = length if newline == -1 else newline
            continue
        if sql.startswith("/*", index):
            close = sql.find("*/", index)
            index = length if close == -1 else close + 2
            continue
        if char == ";":
            statements.append("".join(buf))
            buf = []
            index += 1
            continue
        buf.append(char)
        index += 1

    statements.append("".join(buf))
    return [stripped for stripped in (s.strip() for s in statements) if stripped]
