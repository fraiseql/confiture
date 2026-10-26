"""Migration accompaniment validation.

Validates that DDL schema changes are accompanied by migration files.
Useful for pre-commit hooks and CI/CD pipelines.
"""

from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from confiture.core._migrator.discovery import changed_migrations
from confiture.core.ddl_objects import BODY_KINDS
from confiture.core.function_body_checker import FunctionBodyChecker, FunctionBodyViolation
from confiture.core.function_signature_checker import (
    FunctionSignatureChecker,
    FunctionSignatureViolation,
)
from confiture.core.function_signature_drift import routines_of
from confiture.core.git import GitRepository, root_relative
from confiture.core.git_schema import GitSchemaDiffer
from confiture.core.schema_change import (
    CheckConstraintAdded,
    CheckConstraintDropped,
    ColumnAdded,
    ColumnDefaultChanged,
    ColumnDropped,
    ColumnNotNullValidityChanged,
    ColumnNullabilityChanged,
    ColumnOrderChanged,
    ColumnRenamed,
    ColumnTypeChanged,
    DependentsDropped,
    DependentsRecreated,
    EnumTypeAdded,
    EnumTypeDropped,
    EnumValuesChanged,
    ExclusionConstraintAdded,
    ExclusionConstraintDropped,
    ForeignKeyAdded,
    ForeignKeyDropped,
    IndexAdded,
    IndexDropped,
    ObjectAdded,
    ObjectDropped,
    ObjectReplaced,
    PrimaryKeyAdded,
    PrimaryKeyDropped,
    SchemaChange,
    SequenceAdded,
    SequenceDropped,
    TableAdded,
    TableDropped,
    TableRenamed,
    UniqueConstraintAdded,
    UniqueConstraintDropped,
)
from confiture.exceptions import DifferError, SchemaError
from confiture.models.git import MigrationAccompanimentReport

if TYPE_CHECKING:
    from confiture.core.schema_model import Routine


def is_body_change(change: SchemaChange) -> bool:
    """Whether *change* is a routine redefined in place — a *body* edit by another name.

    ``--require-migration-bodies`` (#178) reports these and is off by default, so
    the gate drops them unless that flag is on: reporting them unconditionally
    would turn a deliberate opt-in into an always-on check. Adding and dropping a
    routine are not body changes. They are the object's *existence*, which nothing
    else in this gate reports, and which #288 is about.
    """
    match change:
        case ObjectReplaced(ref=ref):
            return ref.kind in BODY_KINDS
        case ObjectAdded() | ObjectDropped():
            return False
        case DependentsDropped() | DependentsRecreated():
            # How a migration writes a column change, not a body edited in place.
            return False
        case TableAdded() | TableDropped() | TableRenamed():
            return False
        case (
            ColumnAdded()
            | ColumnDropped()
            | ColumnRenamed()
            | ColumnTypeChanged()
            | ColumnNullabilityChanged()
            | ColumnNotNullValidityChanged()
            | ColumnDefaultChanged()
            | ColumnOrderChanged()
        ):
            return False
        case (
            IndexAdded()
            | IndexDropped()
            | ForeignKeyAdded()
            | ForeignKeyDropped()
            | CheckConstraintAdded()
            | CheckConstraintDropped()
            | UniqueConstraintAdded()
            | PrimaryKeyAdded()
            | UniqueConstraintDropped()
            | PrimaryKeyDropped()
            | ExclusionConstraintAdded()
            | ExclusionConstraintDropped()
        ):
            return False
        case (
            EnumTypeAdded()
            | EnumTypeDropped()
            | EnumValuesChanged()
            | SequenceAdded()
            | SequenceDropped()
        ):
            return False
        case _:
            assert_never(change)


def _touches_routines(changes: list[SchemaChange]) -> bool:
    """Whether the engine found a routine added, dropped or redefined.

    Every violation the signature and body checks report is one of these: a
    retype is a drop and an add in two signature buckets, a body edit a
    redefinition. Without one there is nothing for either check to read.
    """
    return any(
        isinstance(change, ObjectAdded | ObjectDropped | ObjectReplaced)
        and change.ref.kind in BODY_KINDS
        for change in changes
    )


def _without_body_changes(changes: list[SchemaChange]) -> list[SchemaChange]:
    """The changes the gate acts on when ``--require-migration-bodies`` is off."""
    return [change for change in changes if not is_body_change(change)]


class MigrationAccompanimentChecker:
    """Check if DDL changes are accompanied by migration files.

    When schema changes, there should be corresponding migration files
    that explain how to apply those changes to existing databases.

    Attributes:
        env: Environment name
        repo_path: Repository root directory
        git_repo: GitRepository instance
        differ: GitSchemaDiffer instance

    Example:
        >>> checker = MigrationAccompanimentChecker("local", Path("."))
        >>> report = checker.check_accompaniment("origin/main", "HEAD")
        >>> if not report.is_valid:
        ...     print(f"Error: DDL without migrations: {report.summary()}")
    """

    def __init__(
        self,
        env: str,
        repo_path: Path | None = None,
        *,
        differ: GitSchemaDiffer | None = None,
        migrations_dir: Path = Path("db/migrations"),
    ):
        """Initialize accompaniment checker.

        Args:
            env: Environment name (e.g., "local", "production")
            repo_path: The project's directory, in its repository (default: current directory)
            differ: The differ to compare refs with — one shared with another
                check reads each tree once; a new one by default.
            migrations_dir: Where ``migrate up`` reads the migrations, relative to
                *repo_path* — the same ``--migrations-dir``.
        """
        self.env = env
        self.repo_path = repo_path or Path.cwd()
        self.migrations_dir = self.repo_path / migrations_dir
        self.git_repo = GitRepository(self.repo_path)
        self.differ = differ or GitSchemaDiffer(env, self.repo_path)

    def check_accompaniment(
        self,
        base_ref: str,
        target_ref: str = "HEAD",
        *,
        check_bodies: bool = False,
        two_dot: bool = False,
    ) -> MigrationAccompanimentReport:
        """Check if DDL changes are accompanied by migrations.

        Validates:
        1. Detects DDL changes between refs: the build at the point
           *target_ref* forked from *base_ref*, against the build at *target_ref*
        2. Finds new migration files between refs
        3. Reports whether changes are properly accompanied, a changed routine
           compared across the two trees whole, whichever file holds it

        Args:
            base_ref: Base git reference (e.g., "origin/main"). What the branch
                changed is read from its merge base with *target_ref*, so a
                change made on the base after the fork is not the branch's.
            target_ref: Target git reference (default "HEAD")
            check_bodies: Also flag function *body* changes not carried by a
                migration (#178). Off by default — opt-in via
                ``--require-migration-bodies``.
            two_dot: Diff ``base..target`` instead of ``base...target``. Required
                when *target_ref* is a tree rather than a commit — the staged
                index (#184) — because a symmetric difference has to compute a
                merge base and git rejects a tree there. Callers passing this
                are expected to have resolved *base_ref* to the merge base
                themselves, which is what makes the two forms equivalent.

        Returns:
            MigrationAccompanimentReport with validation results

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If git operations fail

        Example:
            >>> checker = MigrationAccompanimentChecker("local")
            >>> report = checker.check_accompaniment("HEAD~1", "HEAD")
            >>> print(f"Has DDL: {report.has_ddl_changes}")
            >>> print(f"Has migrations: {report.has_new_migrations}")
            >>> print(f"Valid: {report.is_valid}")
        """
        # Get new migration files regardless of whether schema parsing succeeds
        new_migrations = self._get_new_migrations(base_ref, target_ref, two_dot=two_dot)
        # A two-dot caller has resolved the merge base already (see two_dot).
        anchor = base_ref if two_dot else self._fork_point(base_ref, target_ref)

        try:
            diff = self.differ.compare_refs(anchor, target_ref)
        except (SchemaError, DifferError) as exc:
            # A schema PostgreSQL rejects (DIFFER_400), or one the differ cannot
            # compare (a quoted name, an index read before its table): the check
            # could not run. It is reported, under the error's own code, rather
            # than raised, and `is_valid` is False because a check that could not
            # run has not passed (#288). A git failure is not this, and propagates.
            return MigrationAccompanimentReport(
                has_ddl_changes=False,
                has_new_migrations=len(new_migrations) > 0,
                migration_error=f"{exc.error_code} {exc.message}",
                base_ref=base_ref,
                target_ref=target_ref,
            )

        signature_violations: list[FunctionSignatureViolation] = []
        body_violations: list[FunctionBodyViolation] = []
        if _touches_routines(diff.changes):
            old, new = self._routines_at(anchor), self._routines_at(target_ref)
            migrations = [self._repo_root / path for path in new_migrations]
            # A parameter type change needs a DROP FUNCTION of the old signature.
            signature_violations = FunctionSignatureChecker().check(old, new, migrations)
            if check_bodies:
                # A body edit needs a migration that re-defines the routine.
                body_violations = FunctionBodyChecker().check(old, new, migrations)

        ddl_changes = diff.changes if check_bodies else _without_body_changes(diff.changes)

        return MigrationAccompanimentReport(
            has_ddl_changes=bool(ddl_changes),
            has_new_migrations=len(new_migrations) > 0,
            ddl_changes=[change.to_wire() for change in ddl_changes],
            new_migration_files=new_migrations,
            base_ref=base_ref,
            target_ref=target_ref,
            signature_violations=signature_violations,
            body_violations=body_violations,
            warnings=diff.warnings,
        )

    def _fork_point(self, base_ref: str, target_ref: str) -> str:
        """Where *target_ref* left *base_ref*: what the branch changed is read from there.

        The tip of *base_ref* would charge the branch with every change made on
        the base since it forked. The migrations are listed three-dot, from the
        same point. With no common ancestor, the tip.
        """
        return self.git_repo.get_merge_base(base_ref, target_ref) or base_ref

    def _routines_at(self, ref: str) -> list[Routine]:
        """The routines *ref*'s build declares: the tree ``compare_refs`` has just read."""
        return routines_of(self.differ.builder.read_at_ref(ref))

    @cached_property
    def _repo_root(self) -> Path:
        """Where the paths git lists are relative to."""
        return self.git_repo.get_repo_root()

    def _changed_files(self, base_ref: str, target_ref: str, *, two_dot: bool) -> list[Path]:
        """Files changed between the refs and present at the target, two-dot for a tree."""
        if two_dot:
            return self.git_repo.get_changed_files_two_dot(base_ref, target_ref, diff_filter="d")
        return self.git_repo.get_changed_files(base_ref, target_ref, diff_filter="d")

    def _get_new_migrations(
        self, base_ref: str, target_ref: str = "HEAD", *, two_dot: bool = False
    ) -> list[Path]:
        """Get list of new migration files between refs.

        A changed file is one when ``migrate up`` would run it from the
        migrations directory: directly in it, named as a migration, and present
        at the target (a deleted migration carries nothing).

        Args:
            base_ref: Base git reference
            target_ref: Target git reference

        Returns:
            List of new/modified migration file paths

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If git operations fail
        """
        changed = self._changed_files(base_ref, target_ref, two_dot=two_dot)
        directory = root_relative(self.migrations_dir, self._repo_root.resolve())
        return changed_migrations(changed, directory)
