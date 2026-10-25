"""The one definition of a seed path.

A path is a seed path when any component at or below the project root contains
``seed`` or ``seeds`` as a whole token — delimited by the component's start/end
or a ``_`` / ``-`` separator. This recognises ordering-prefixed layouts
(``30_seed_backend``, ``seed_common``, ``10-seeds``) and rejects look-alikes
(``seedling``, ``proceeds``, ``reseed_tools``). The builder's categorisation,
``build --schema-only`` and the sequential file count all ask here.

A *seed file* is a file on a seed path that does more than create schema
objects: the prep-seed layout keeps its staging tables in ``prep_seed/``, and a
file of ``CREATE TABLE``s there is schema wherever its directory's name puts it
(#748).
"""

import re
from pathlib import Path, PurePath
from typing import Any

from pglast.parser import ParseError

from confiture.core.sql_lexer import code_tokens, parse_file, skip_leading_comments, statement_spans

_SEED_DIR_RE = re.compile(r"(?:^|[_-])seeds?(?:$|[_-])")


def _components(path: Path, anchor: Path | None) -> tuple[str, ...]:
    """*path*'s components below *anchor*, or all of them for a path outside it."""
    if anchor is not None:
        try:
            return path.relative_to(anchor).parts
        except ValueError:
            pass
    return path.parts


def is_seed_path(path: Path | str, *, anchor: Path | None = None) -> bool:
    """True when a component of *path* (below *anchor*, if given) is a seed directory.

    ``anchor`` is the directory above the include root: the absolute prefix
    above a project must not count, or a project under ``~/my_seed_app/`` would
    have every file classified as a seed. A path outside *anchor* is judged on
    all of its components so a genuine seed directory is never missed.
    """
    return any(_SEED_DIR_RE.search(part.lower()) for part in _components(Path(path), anchor))


def seed_relative(path: Path, *, anchor: Path | None = None) -> PurePath:
    """*path* below the first seed directory in it — what ``seed apply --seeds-dir`` sees.

    ``db/seeds/common/10_users.sql`` is ``common/10_users.sql``, the path a seed
    profile's globs see when ``seed apply`` reads ``db/seeds``, so a profile
    selects the same files whichever command applies it. A path with no seed
    directory below *anchor* is its bare name.
    """
    parts = _components(path, anchor)
    for index, part in enumerate(parts[:-1]):
        if _SEED_DIR_RE.search(part.lower()):
            return PurePath(*parts[index + 1 :])
    return PurePath(path.name)


#: Statements that create (or describe) a persistent schema object and write no row.
_CREATES = frozenset(
    {
        "CommentStmt",
        "CompositeTypeStmt",
        "CreateDomainStmt",
        "CreateEnumStmt",
        "CreateExtensionStmt",
        "CreateFunctionStmt",
        "CreateSchemaStmt",
        "CreateSeqStmt",
        "CreateStmt",
        "CreateTrigStmt",
        "IndexStmt",
        "ViewStmt",
    }
)


def _creates_a_persistent_object(stmt: Any) -> bool:
    if type(stmt).__name__ not in _CREATES:
        return False
    relation = getattr(stmt, "relation", None) or getattr(stmt, "view", None)
    relation = relation or getattr(stmt, "sequence", None)
    return relation is None or relation.relpersistence != "t"


#: The first keyword of every statement :data:`_CREATES` holds.
_CREATE_VERBS = frozenset({"CREATE", "COMMENT"})


def _opens_with_create(text: str, start: int = 0) -> bool:
    """Whether the statement at *start* begins ``CREATE`` or ``COMMENT``: its first token only."""
    at = skip_leading_comments(text, start)
    first = code_tokens(text[at : at + 16])
    return bool(first) and first[0].name in _CREATE_VERBS


def _only_creates(path: Path) -> bool:
    """Whether every statement of *path* creates a persistent schema object, and one does.

    A statement is parsed only when its first keyword is ``CREATE`` or
    ``COMMENT``, so a seed file of a million ``INSERT`` rows is answered by its
    first token. A file that cannot be read keeps its path's verdict: the build
    that reads it says why.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return False
    if not _opens_with_create(text):
        return False
    spans = statement_spans(text)
    for span in spans:
        if not _opens_with_create(text, span.start):
            return False
        try:
            parsed = parse_file(text[span])
        except ParseError:
            return False
        if not all(_creates_a_persistent_object(raw.stmt) for raw in parsed.statements):
            return False
    return bool(spans)


def is_seed_file(path: Path, *, anchor: Path | None = None) -> bool:
    """True when *path* is on a seed path (:func:`is_seed_path`) and does more than create objects.

    A file that only creates persistent schema objects — ``CREATE TABLE``,
    ``CREATE INDEX``, a view, a routine, a type, and ``COMMENT ON`` them — is
    schema even under ``seeds/`` or ``prep_seed/``. Anything else there stays a
    seed: a row written, a ``TEMP`` table, an ``ALTER TABLE … DISABLE TRIGGER``,
    a ``setval``, a file the parser rejects.
    """
    return is_seed_path(path, anchor=anchor) and not _only_creates(path)
