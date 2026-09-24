"""The one definition of a seed path.

A path is a seed path when any component at or below the project root contains
``seed`` or ``seeds`` as a whole token — delimited by the component's start/end
or a ``_`` / ``-`` separator. This recognises ordering-prefixed layouts
(``30_seed_backend``, ``seed_common``, ``10-seeds``) and rejects look-alikes
(``seedling``, ``proceeds``, ``reseed_tools``). The builder's categorisation,
``build --schema-only`` and the sequential file count all ask here.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePath

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
