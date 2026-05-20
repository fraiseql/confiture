"""SQL function tree renumber — safe file-move with cross-reference rewriting.

Provides :class:`TreeRenumber`, which moves a single SQL file or an entire
subtree to a new location, allocates sort-stable filenames at the target
via :class:`~confiture.core.tree_allocator.TreeAllocator`, finds calls to
renamed functions in other schema files, and rewrites them.

Cross-reference detection and rewriting
----------------------------------------
Function names are **derived from filenames** (the stem after stripping the
numeric prefix).  For example, ``00042_create_item.sql`` implies the
function name ``create_item``.

:attr:`RenumberResult.ref_rewrites` lists every other ``.sql`` file that
calls the moved function.  When the function stem changes (e.g.,
``create_item`` → ``update_item``), those references are rewritten
automatically.  When the stem is unchanged (pure prefix renumber), the list
is informational only — no rewrites occur.

*Dangling references* are occurrences of the old name that survive the
rewrite pass.  This happens when the name appears inside a **single-quoted
string literal**, which the rewriter intentionally leaves untouched to avoid
corrupting dynamic SQL strings.  :attr:`RenumberResult.dangling_refs` lists
them; the CLI exits with code 2 when any are present.

Example::

    from pathlib import Path
    from confiture.core.tree_renumber import TreeRenumber

    renumber = TreeRenumber(Path("db/schema"))
    plans = renumber.build_plans(
        Path("db/schema/functions/00001_create_item.sql"),
        Path("db/schema/functions/00005_update_item.sql"),
    )
    result = renumber.execute(plans)
    if result.dangling_refs:
        print("Manual fixes needed:", result.dangling_refs)
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
from pathlib import Path

from confiture.core.tree_allocator import PrefixConfig, TreeAllocator

# Matches a leading numeric (decimal or hex) prefix followed by "_".
_PREFIX_RE = re.compile(r"^[0-9a-fA-F]+_")

# Matches a single-quoted SQL string literal (handles escaped '' inside).
_STRING_LITERAL_RE = re.compile(r"'[^']*(?:''[^']*)*'")


def _stem_from_path(path: Path) -> str:
    """Return the function-name stem of *path* by stripping the numeric prefix.

    Args:
        path: A ``.sql`` file path (full or bare filename).

    Returns:
        Filename stem with the ``<digits>_`` prefix removed.
        Returns the plain stem when no prefix is found.

    Examples::

        _stem_from_path(Path("00042_create_item.sql"))  # → "create_item"
        _stem_from_path(Path("0001a_create.sql"))        # → "create"
        _stem_from_path(Path("create_item.sql"))         # → "create_item"
    """
    return _PREFIX_RE.sub("", path.stem)


@dataclasses.dataclass
class RenumberPlan:
    """A single file-move plan.

    Attributes:
        old_path: Absolute source path.
        new_path: Absolute target path (fully resolved, including filename).
        old_name: Function name derived from *old_path* stem.
        new_name: Function name derived from *new_path* stem.
            When ``old_name == new_name`` no reference rewriting is done.
    """

    old_path: Path
    new_path: Path
    old_name: str
    new_name: str


@dataclasses.dataclass
class RefRewrite:
    """A reference that was (or in dry-run: would be) processed.

    When ``old_name == new_name`` this is informational (pure renumber, no
    rewrite needed).  When they differ the file was (or would be) rewritten.

    Attributes:
        ref_file: File containing the reference.
        old_name: Name that was (or would be) replaced.
        new_name: Name that replaced (or would replace) it.
    """

    ref_file: Path
    old_name: str
    new_name: str


@dataclasses.dataclass
class RenumberResult:
    """The outcome of a :meth:`TreeRenumber.execute` call.

    Attributes:
        plans: The plans that were executed.
        ref_rewrites: Other schema files that reference the moved function.
            Entries with ``old_name == new_name`` are informational;
            entries where they differ represent actual rewrites.
        dangling_refs: ``(file, old_name)`` pairs where *old_name* still
            appears (e.g. inside string literals) after the rewrite pass.
            Require manual correction.  Non-empty → CLI exits with code 2.
        cross_repo_refs: Paths outside the ``db/`` tree that mention one of
            the moved filenames by name.  Populated only when ``force=True``
            is passed; otherwise ``execute`` raises ``ValueError`` before
            returning.
    """

    plans: list[RenumberPlan]
    ref_rewrites: list[RefRewrite]
    dangling_refs: list[tuple[Path, str]]
    cross_repo_refs: list[Path] = dataclasses.field(default_factory=list)


class TreeRenumber:
    """Moves SQL files within a schema tree and rewrites cross-references.

    Args:
        schema_dir: Root of the schema tree.  All source and target paths
            must be within this directory.
        repo_root: Optional repository root for cross-repo reference scanning.
            When provided, :meth:`execute` searches the repo for occurrences
            of the old filename outside the ``db/`` tree and refuses to
            proceed without ``force=True``.  When ``None`` the cross-repo
            scan is skipped (best-effort default for non-git or unusual
            project layouts).
    """

    def __init__(self, schema_dir: Path, repo_root: Path | None = None) -> None:
        self.schema_dir = schema_dir.resolve()
        self.repo_root = repo_root.resolve() if repo_root is not None else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_plans(self, old_path: Path, new_path: Path) -> list[RenumberPlan]:
        """Build renumber plans without executing them.

        Accepts three combinations:

        - **file → file**: Move one file to an exact target path.
        - **file → dir**: Allocate the next prefix in *new_path*, keeping
          the old filename stem.
        - **dir → dir**: For each ``.sql`` file in *old_path* (sorted),
          allocate a sequential prefix in *new_path*.

        Args:
            old_path: Source file or directory.  Must exist.
            new_path: Target file path or directory.

        Returns:
            List of :class:`RenumberPlan` (one per moved file).

        Raises:
            ValueError: If *old_path* does not exist.
        """
        old_resolved = old_path.resolve()
        new_resolved = new_path.resolve()

        if not old_resolved.exists():
            raise ValueError(f"Source does not exist: {old_resolved}")

        if old_resolved.is_dir():
            return self._plans_for_subtree(old_resolved, new_resolved)
        return self._plans_for_file(old_resolved, new_resolved)

    def execute(
        self,
        plans: list[RenumberPlan],
        dry_run: bool = False,
        force: bool = False,
    ) -> RenumberResult:
        """Execute *plans*, optionally in dry-run mode.

        Steps:

        1. Refuse if any plan would clobber an existing file at the target.
        2. Refuse if any moved filename is referenced outside the ``db/``
           tree (skipped when ``repo_root`` is None or ``force=True``).
        3. Collect all ``.sql`` files in the schema tree that are not part
           of this move (potential reference files).
        4. Move files (skipped when *dry_run*).
        5. For each plan, scan other files for calls to *old_name* and
           record :class:`RefRewrite` entries.
        6. When *old_name != new_name* and *not dry_run*: rewrite the
           references outside string literals.
        7. Detect dangling references that survive the rewrite.

        Args:
            plans: Plans produced by :meth:`build_plans`.
            dry_run: When *True*, no files are modified.
            force: When *True*, skip the cross-repo reference refusal.
                Cross-repo hits are still reported on the result.

        Returns:
            :class:`RenumberResult` summarising moves, rewrites, dangling
            references, and any cross-repo references that were detected.

        Raises:
            ValueError: If a plan would clobber an existing file, or if
                cross-repo references exist and ``force`` is not set.
        """
        moved_old = {p.old_path for p in plans}
        moved_new = {p.new_path for p in plans}

        # 1. Collision check — refuse to clobber existing files.
        for plan in plans:
            if plan.new_path.exists() and plan.new_path.resolve() != plan.old_path.resolve():
                raise ValueError(
                    f"renumber collision: target {plan.new_path!s} already exists "
                    "— refusing to overwrite"
                )

        # 2. Cross-repo reference scan.
        cross_repo_refs = self._scan_cross_repo_refs(plans) if self.repo_root else []
        if cross_repo_refs and not force:
            ref_list = "\n  ".join(str(p) for p in cross_repo_refs)
            raise ValueError(
                "renumber refused: filename(s) referenced outside the db/ tree:\n  "
                f"{ref_list}\nUse force=True (CLI: --force) to proceed anyway."
            )

        # Gather other schema files before any moves.
        other_files = [
            p.resolve()
            for p in self.schema_dir.rglob("*.sql")
            if p.resolve() not in moved_old and p.resolve() not in moved_new
        ]

        # Move files.
        if not dry_run:
            for plan in plans:
                plan.new_path.parent.mkdir(parents=True, exist_ok=True)
                plan.old_path.rename(plan.new_path)

        # Find refs and (optionally) rewrite them.
        ref_rewrites: list[RefRewrite] = []
        for plan in plans:
            for sql_file in other_files:
                content = sql_file.read_text()
                if _references(content, plan.old_name):
                    ref_rewrites.append(
                        RefRewrite(
                            ref_file=sql_file,
                            old_name=plan.old_name,
                            new_name=plan.new_name,
                        )
                    )
                    needs_rewrite = plan.old_name != plan.new_name
                    if needs_rewrite and not dry_run:
                        sql_file.write_text(_rewrite(content, plan.old_name, plan.new_name))

        # Detect dangling refs: old_name still present after rewriting.
        dangling_refs: list[tuple[Path, str]] = []
        if not dry_run:
            seen: set[tuple[Path, str]] = set()
            for rw in ref_rewrites:
                if rw.old_name == rw.new_name:
                    continue
                key = (rw.ref_file, rw.old_name)
                if key in seen:
                    continue
                seen.add(key)
                remaining = rw.ref_file.read_text()
                if _references(remaining, rw.old_name):
                    dangling_refs.append((rw.ref_file, rw.old_name))

        return RenumberResult(
            plans=plans,
            ref_rewrites=ref_rewrites,
            dangling_refs=dangling_refs,
            cross_repo_refs=cross_repo_refs,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scan_cross_repo_refs(self, plans: list[RenumberPlan]) -> list[Path]:
        """Find non-``db/`` files mentioning any moved filename.

        Uses ``git grep -l`` when ``repo_root`` is inside a git work tree,
        otherwise falls back to a filesystem walk.  Both paths return only
        files outside the ``db/`` subtree, since references inside ``db/``
        are handled by the regular ref-rewrite path.
        """
        if self.repo_root is None:
            return []
        filenames = [p.old_path.name for p in plans]
        if not filenames:
            return []
        db_root = self.repo_root / "db"

        # Prefer git grep — fast and respects .gitignore.
        hits = self._git_grep_filenames(filenames)
        if hits is None:
            hits = self._fs_walk_filenames(filenames)

        # Exclude paths inside db/, and the moved files themselves.
        out: list[Path] = []
        seen: set[Path] = set()
        for hit in hits:
            resolved = hit.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                resolved.relative_to(db_root.resolve())
            except ValueError:
                out.append(resolved)
                continue
            # Inside db/ — ignored.
        return sorted(out)

    def _git_grep_filenames(self, filenames: list[str]) -> list[Path] | None:
        """Run ``git grep -l`` for the union of *filenames*.

        Returns *None* when the repo root is not a git work tree (caller
        should fall back to fs walk).
        """
        if self.repo_root is None:
            return None
        # Filenames containing newlines would corrupt ``git grep -l``'s
        # newline-delimited output (we'd split a single match into two paths).
        # Reject them rather than scan with split risk.
        if any("\n" in f or "\r" in f for f in filenames):
            return None
        # Compose an OR pattern that git grep can handle.
        pattern = "|".join(re.escape(f) for f in filenames)
        try:
            proc = subprocess.run(
                ["git", "grep", "-lE", "--", pattern],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        # Exit 128 → not a git repo.  Exit 1 → no matches (treated as empty).
        if proc.returncode == 128:
            return None
        if proc.returncode not in (0, 1):
            return None
        return [self.repo_root / line for line in proc.stdout.splitlines() if line]

    def _fs_walk_filenames(self, filenames: list[str]) -> list[Path]:
        """Filesystem fallback: walk repo_root, grep each file for *filenames*."""
        if self.repo_root is None:
            return []
        needles = [re.escape(name) for name in filenames]
        pattern = re.compile("|".join(needles))
        hits: list[Path] = []
        for path in self.repo_root.rglob("*"):
            if not path.is_file():
                continue
            # Skip likely-binary files and large blobs.
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            if pattern.search(text):
                hits.append(path)
        return hits

    def _plans_for_file(self, old_path: Path, new_path: Path) -> list[RenumberPlan]:
        if new_path.is_dir() or (not new_path.suffix and not new_path.exists()):
            stem = _stem_from_path(old_path)
            new_path = TreeAllocator(self.schema_dir).alloc(new_path, verb=stem)
        return [
            RenumberPlan(
                old_path=old_path,
                new_path=new_path,
                old_name=_stem_from_path(old_path),
                new_name=_stem_from_path(new_path),
            )
        ]

    def _plans_for_subtree(self, old_dir: Path, new_dir: Path) -> list[RenumberPlan]:
        """Build plans for all .sql files in *old_dir*, sorted by name.

        Allocates sequentially into *new_dir* without touching disk, so that
        dry-run mode leaves *new_dir* completely empty.
        """
        sql_files = sorted(
            (f for f in old_dir.iterdir() if f.suffix == ".sql"),
            key=lambda f: f.name,
        )
        if not sql_files:
            return []

        # Detect or default prefix config from the target directory.
        allocator = TreeAllocator(self.schema_dir)
        if new_dir.exists():
            config = allocator._detect_config(new_dir)
            existing = allocator._collect_prefixes(new_dir, config.scheme)
        else:
            config = PrefixConfig()
            existing = []

        next_val = (max(existing) + config.step) if existing else config.start

        plans: list[RenumberPlan] = []
        for sql_file in sql_files:
            stem = _stem_from_path(sql_file)
            prefix = TreeAllocator._format_prefix(next_val, config)
            new_path = new_dir / f"{prefix}_{stem}.sql"
            plans.append(
                RenumberPlan(
                    old_path=sql_file,
                    new_path=new_path,
                    old_name=stem,
                    new_name=stem,
                )
            )
            next_val += config.step

        return plans


# ---------------------------------------------------------------------------
# Module-level regex utilities
# ---------------------------------------------------------------------------


def _references(content: str, name: str) -> bool:
    """Return *True* if *content* contains a call to *name*.

    Searches the full content including string literals, so that
    string-literal occurrences can be detected as dangling refs after
    an outside-literal rewrite.
    """
    pattern = re.compile(rf"\b{re.escape(name)}\s*\(")
    return bool(pattern.search(content))


def _rewrite(content: str, old_name: str, new_name: str) -> str:
    """Replace *old_name* with *new_name* **outside** single-quoted string literals.

    String literals are preserved verbatim so that dynamic SQL strings
    (e.g. ``EXECUTE 'SELECT old_name()'``) are flagged as dangling refs
    rather than silently mangled.
    """
    pattern = re.compile(rf"\b{re.escape(old_name)}\b")
    parts: list[str] = []
    last_end = 0
    for m in _STRING_LITERAL_RE.finditer(content):
        # Non-string segment: apply substitution.
        parts.append(pattern.sub(new_name, content[last_end : m.start()]))
        # String literal segment: keep verbatim.
        parts.append(m.group())
        last_end = m.end()
    # Trailing non-string segment.
    parts.append(pattern.sub(new_name, content[last_end:]))
    return "".join(parts)
