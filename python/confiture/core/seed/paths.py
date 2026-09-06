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
from pathlib import Path

_SEED_DIR_RE = re.compile(r"(?:^|[_-])seeds?(?:$|[_-])")


def is_seed_path(path: Path | str, *, anchor: Path | None = None) -> bool:
    """True when a component of *path* (below *anchor*, if given) is a seed directory.

    ``anchor`` is the directory above the include root: the absolute prefix
    above a project must not count, or a project under ``~/my_seed_app/`` would
    have every file classified as a seed. A path outside *anchor* is judged on
    all of its components so a genuine seed directory is never missed.
    """
    candidate = Path(path)
    components: tuple[str, ...]
    if anchor is not None:
        try:
            components = candidate.relative_to(anchor).parts
        except ValueError:
            components = candidate.parts
    else:
        components = candidate.parts
    return any(_SEED_DIR_RE.search(part.lower()) for part in components)
