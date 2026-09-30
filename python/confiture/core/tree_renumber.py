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

Files a migration reads
-----------------------
A migration that reads a schema file at run time (``(SCHEMA_DIR /
"0219_x.sql").read_text()``) pins its path: rewriting the migration changes its
checksum, and not rewriting it breaks every replay. :meth:`TreeRenumber.execute`
asks ``core/migration_reads`` which files the migrations read and refuses to move
one (``VALID_003``), ``force`` or not, until ``migrate squash`` archives the
migration. A read whose path the static evaluator cannot fix might be one, so it
refuses too (``VALID_004``), unless ``force``.

Compaction
----------
:meth:`TreeRenumber.build_compact_plans` gives a directory's numbered children,
files and subdirectories alike, the lowest contiguous prefixes in their build
order. It refuses (``VALID_005``) when the new names would change the order
``confiture build`` reads the tree in, for instance against an unnumbered sibling
whose name sorts between an old prefix and its new one.

An explicit move may change the order on purpose (it is how a file is made to build
earlier), so it is not refused; :attr:`RenumberResult.reordered` names the files each
moved one now builds before or after.

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

from confiture.core import sql_lexer
from confiture.core.builder import files_under
from confiture.core.idempotency.python_migration_extractor import is_migration_file
from confiture.core.migration_reads import MigrationRead, reads
from confiture.core.tree_allocator import PrefixConfig, PrefixScheme, TreeAllocator
from confiture.core.tree_prefix import is_hex_group, is_numbered, prefix_text
from confiture.exceptions import ValidationError


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
    raw = prefix_text(path.stem)
    return path.stem if raw is None else path.stem[len(raw) + 1 :]


@dataclasses.dataclass
class RenumberPlan:
    """A single move: a file, or a whole directory when compacting.

    Attributes:
        old_path: Absolute source path.
        new_path: Absolute target path (fully resolved, including filename).
        old_name: Function name derived from *old_path* stem; empty for a
            directory, which names no function.
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


@dataclasses.dataclass(frozen=True)
class OrderChange:
    """A moved file whose place in the build changes against the files that stay.

    Attributes:
        old_path: The file as it is now.
        new_path: Where it goes.
        now_before: Files it built after and now builds before.
        now_after: Files it built before and now builds after.
    """

    old_path: Path
    new_path: Path
    now_before: tuple[Path, ...]
    now_after: tuple[Path, ...]


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
        unresolved_reads: Reads by a migration whose path is not static, which
            ``force=True`` proceeded past.
        reordered: Each moved file whose place in the build changes. Reported,
            not refused: building a file earlier or later is what a move is for.
    """

    plans: list[RenumberPlan]
    ref_rewrites: list[RefRewrite]
    dangling_refs: list[tuple[Path, str]]
    cross_repo_refs: list[Path] = dataclasses.field(default_factory=list)
    unresolved_reads: list[MigrationRead] = dataclasses.field(default_factory=list)
    reordered: list[OrderChange] = dataclasses.field(default_factory=list)


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
        migrations_dir: The migrations whose file reads pin a path. ``None``,
            or a directory that does not exist, pins nothing.
    """

    def __init__(
        self,
        schema_dir: Path,
        repo_root: Path | None = None,
        migrations_dir: Path | None = None,
    ) -> None:
        self.schema_dir = schema_dir.resolve()
        self.repo_root = repo_root.resolve() if repo_root is not None else None
        self.migrations_dir = migrations_dir

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

    def build_compact_plans(self, directory: Path) -> list[RenumberPlan]:
        """Plans giving *directory*'s numbered children the lowest contiguous prefixes.

        Files and subdirectories are numbered together, in the order the build
        reads them, from 1 at the directory's modal prefix width and in its base.
        A child already at its prefix does not move; a directory without gaps
        gives no plan.

        Raises:
            ValidationError: ``VALID_005`` when the new names would change the
                order ``confiture build`` reads the tree in.
        """
        directory = directory.resolve()
        children = sorted(
            (
                child
                for child in directory.iterdir()
                if is_numbered(child.name) and (child.is_dir() or child.suffix == ".sql")
            ),
            key=lambda child: child.name,
        )
        if not children:
            return []
        raws = [prefix_text(child.name) or "" for child in children]
        widths = [len(raw) for raw in raws]
        config = PrefixConfig(
            scheme=PrefixScheme.HEX
            if is_hex_group(child.name for child in children)
            else PrefixScheme.DECIMAL,
            width=max(set(widths), key=widths.count),
        )
        plans: list[RenumberPlan] = []
        for value, (child, raw) in enumerate(zip(children, raws, strict=True), start=config.start):
            new_path = directory / (
                TreeAllocator._format_prefix(value, config) + child.name[len(raw) :]
            )
            if new_path.name == child.name:
                continue
            stem = "" if child.is_dir() else _stem_from_path(child)
            new_stem = "" if child.is_dir() else _stem_from_path(new_path)
            plans.append(RenumberPlan(child, new_path, stem, new_stem))
        self._refuse_reordering(plans)
        return plans

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

        # 1. Collision check — refuse to clobber a file that is not itself moving.
        for plan in plans:
            if plan.new_path.exists() and plan.new_path.resolve() not in moved_old:
                raise ValueError(
                    f"renumber collision: target {plan.new_path!s} already exists "
                    "— refusing to overwrite"
                )

        # 2. A file a migration reads is never moved; a read it cannot resolve
        #    might be one.
        unresolved = self._refuse_pinned(plans, force=force)

        # 3. Cross-repo reference scan.
        cross_repo_refs = self._scan_cross_repo_refs(plans) if self.repo_root else []
        if cross_repo_refs and not force:
            ref_list = "\n  ".join(str(p) for p in cross_repo_refs)
            raise ValueError(
                "renumber refused: filename(s) referenced outside the db/ tree:\n  "
                f"{ref_list}\nUse force=True (CLI: --force) to proceed anyway."
            )

        reordered = self.order_changes(plans)

        # Gather other schema files before any moves.
        other_files = [
            p.resolve()
            for p in files_under(self.schema_dir)
            if _moved_by(p.resolve(), plans) is None and p.resolve() not in moved_new
        ]

        # Move files.
        if not dry_run:
            for plan in plans:
                plan.new_path.parent.mkdir(parents=True, exist_ok=True)
                plan.old_path.rename(plan.new_path)

        ref_rewrites = _rewrite_references(plans, other_files, dry_run=dry_run)
        dangling_refs = [] if dry_run else _dangling(ref_rewrites)

        return RenumberResult(
            plans=plans,
            ref_rewrites=ref_rewrites,
            dangling_refs=dangling_refs,
            cross_repo_refs=cross_repo_refs,
            unresolved_reads=unresolved,
            reordered=reordered,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refuse_pinned(self, plans: list[RenumberPlan], *, force: bool) -> list[MigrationRead]:
        """Refuse a move of a file a migration reads; return the reads ``force`` passed."""
        if self.migrations_dir is None or not self.migrations_dir.is_dir():
            return []
        found = [
            read
            for migration in sorted(self.migrations_dir.glob("*.py"))
            if is_migration_file(migration)
            for read in reads(migration)
        ]
        pinned = [r for r in found if r.file is not None and _moved_by(r.file, plans) is not None]
        if pinned:
            listed = "\n  ".join(f"{r.migration.name}:{r.line} reads {r.file}" for r in pinned)
            raise ValidationError(
                "renumber refused: a migration reads the file(s) at their current path, so "
                f"moving them breaks its replay:\n  {listed}",
                error_code="VALID_003",
                resolution_hint=(
                    "Leave the file where it is, or archive the migration with `migrate squash`. "
                    "--force does not override this: rewriting an applied migration changes "
                    "its checksum"
                ),
            )
        unresolved = [r for r in found if r.file is None]
        if unresolved and not force:
            listed = "\n  ".join(f"{r.migration.name}:{r.line}: {r.reason}" for r in unresolved)
            raise ValidationError(
                "renumber refused: a migration reads a path confiture cannot resolve "
                f"statically, so it may read a file this moves:\n  {listed}",
                error_code="VALID_004",
                resolution_hint="Check those reads, then re-run with --force",
            )
        return unresolved

    def order_changes(self, plans: list[RenumberPlan]) -> list[OrderChange]:
        """Each file *plans* move to another place in the build, against the files that stay."""
        before = [path.resolve() for path in files_under(self.schema_dir)]
        was = {path: index for index, path in enumerate(before)}
        will = {
            path: index
            for index, path in enumerate(sorted(before, key=lambda p: _destination(p, plans)))
        }
        staying = [path for path in before if _moved_by(path, plans) is None]
        changes: list[OrderChange] = []
        for path in before:
            if _moved_by(path, plans) is None:
                continue
            now_before = tuple(o for o in staying if was[o] < was[path] and will[o] > will[path])
            now_after = tuple(o for o in staying if was[o] > was[path] and will[o] < will[path])
            if now_before or now_after:
                changes.append(OrderChange(path, _destination(path, plans), now_before, now_after))
        return changes

    def _refuse_reordering(self, plans: list[RenumberPlan]) -> None:
        """Refuse plans whose new names change the order the build reads the tree in."""
        before = [path.resolve() for path in files_under(self.schema_dir)]
        after = sorted(before, key=lambda path: _destination(path, plans))
        if after != before:
            moved = next(a for a, b in zip(after, before, strict=True) if a != b)
            raise ValidationError(
                f"compaction refused: {_destination(moved, plans)} would be built in a "
                "different position than it is now",
                error_code="VALID_005",
                resolution_hint=(
                    "Rename the unnumbered sibling, or renumber the files one at a time"
                ),
            )

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


def _rewrite_references(
    plans: list[RenumberPlan], other_files: list[Path], *, dry_run: bool
) -> list[RefRewrite]:
    """Every other file calling a moved function, rewritten when its name changes."""
    ref_rewrites: list[RefRewrite] = []
    for plan in plans:
        if not plan.old_name:
            continue
        for sql_file in other_files:
            content = sql_file.read_text()
            if not _references(content, plan.old_name):
                continue
            ref_rewrites.append(
                RefRewrite(ref_file=sql_file, old_name=plan.old_name, new_name=plan.new_name)
            )
            if plan.old_name != plan.new_name and not dry_run:
                sql_file.write_text(_rewrite(content, plan.old_name, plan.new_name))
    return ref_rewrites


def _dangling(ref_rewrites: list[RefRewrite]) -> list[tuple[Path, str]]:
    """``(file, old_name)`` where a rewritten name survives the rewrite (a string literal)."""
    dangling: list[tuple[Path, str]] = []
    seen: set[tuple[Path, str]] = set()
    for rw in ref_rewrites:
        key = (rw.ref_file, rw.old_name)
        if rw.old_name == rw.new_name or key in seen:
            continue
        seen.add(key)
        if _references(rw.ref_file.read_text(), rw.old_name):
            dangling.append(key)
    return dangling


def _moved_by(path: Path, plans: list[RenumberPlan]) -> RenumberPlan | None:
    """The plan that moves *path*: its own, or its directory's."""
    return next(
        (plan for plan in plans if path == plan.old_path or path.is_relative_to(plan.old_path)),
        None,
    )


def _destination(path: Path, plans: list[RenumberPlan]) -> Path:
    """Where *path* is once *plans* have run."""
    plan = _moved_by(path, plans)
    if plan is None:
        return path
    return plan.new_path / path.relative_to(plan.old_path)


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
    rather than silently mangled. A dollar-quoted body is code — its
    references are rewritten, its own literals kept.
    """
    pattern = re.compile(rf"\b{re.escape(old_name)}\b")
    return _rewrite_outside_literals(content, pattern, new_name)


def _rewrite_outside_literals(text: str, pattern: re.Pattern[str], new_name: str) -> str:
    parts: list[str] = []
    last = 0
    for token in sql_lexer.tokens(text):
        if token.name != "SCONST":
            continue
        parts.append(pattern.sub(new_name, text[last : token.start]))
        literal = text[token.start : token.end + 1]
        if literal.startswith("$"):
            tag = literal[: literal.index("$", 1) + 1]
            body = literal[len(tag) : len(literal) - len(tag)]
            parts.append(tag + _rewrite_outside_literals(body, pattern, new_name) + tag)
        else:
            parts.append(literal)
        last = token.end + 1
    parts.append(pattern.sub(new_name, text[last:]))
    return "".join(parts)
