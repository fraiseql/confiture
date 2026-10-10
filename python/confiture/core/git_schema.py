"""Schema building and comparison from git refs.

A ref is read the way ``confiture build`` reads the working tree: its include
directories are copied out of the ref's tree into a scratch directory
(``GitRepository.materialise``), and the build's own selection
(``SchemaBuilder._select``) reads the copy — the same files, the same order, the
same text, file by file. Nothing here lists, orders or matches files itself.
"""

import tempfile
from functools import cached_property
from pathlib import Path

from confiture.config.environment import DirectoryConfig, Environment
from confiture.core.builder import SchemaBuilder
from confiture.core.differ import SchemaDiffer
from confiture.core.git import GitRepository
from confiture.core.schema_change import SchemaDiff
from confiture.core.schema_read import SchemaRead, Segment, joined, read_segments
from confiture.core.schema_sources import selection_segments
from confiture.exceptions import GitError


def _rebased(path: Path, root: Path, tree: Path) -> Path:
    """*path*, under the repository *root*, at the same place under the scratch *tree*."""
    return tree / path.relative_to(root)


def _environment_at(env: Environment, root: Path, tree: Path) -> Environment:
    """*env* with its include directories moved from the repository to the scratch *tree*.

    Every other key is carried — ``recursive``, ``include``, ``exclude``,
    ``order``, ``build.sort_mode``. A directory the ref does not hold is an empty
    entry (``auto_discover``), whatever the working tree says: the working tree
    was checked when the environment loaded. An ``exclude_dirs`` entry outside
    the repository is kept as it is; it matches nothing there either.
    """
    include_dirs: list[str | DirectoryConfig] = []
    for item in env.include_dirs:
        if isinstance(item, str):
            include_dirs.append(str(_rebased(Path(item), root, tree)))
        else:
            path = str(_rebased(Path(item.path), root, tree))
            include_dirs.append(item.model_copy(update={"path": path, "auto_discover": True}))
    exclude_dirs = [
        str(_rebased(Path(d), root, tree)) if Path(d).is_relative_to(root) else d
        for d in env.exclude_dirs
    ]
    return env.model_copy(update={"include_dirs": include_dirs, "exclude_dirs": exclude_dirs})


class GitSchemaBuilder:
    """Read the schema a git ref holds, through the build's own selection.

    The environment's configuration comes from the working tree; the files come
    from the ref.

    Attributes:
        env: Environment name
        repo_path: The project directory (any directory inside the repository)
        git_repo: GitRepository instance

    Example:
        >>> builder = GitSchemaBuilder("local", Path("."))
        >>> schema = builder.build_schema_at_ref("origin/main")
        >>> schema_head = builder.build_schema_at_ref("HEAD")
    """

    def __init__(self, env: str, repo_path: Path | None = None):
        """Initialize GitSchemaBuilder.

        Args:
            env: Environment name (e.g., "local", "production")
            repo_path: The project directory (default: current directory)
        """
        self.env = env
        self.repo_path = repo_path or Path.cwd()
        self.git_repo = GitRepository(self.repo_path)
        self._reads: dict[str, SchemaRead] = {}

    @cached_property
    def schema_builder(self) -> SchemaBuilder:
        """The working tree's build: its environment is the one every ref is read with."""
        return SchemaBuilder(self.env, self.repo_path)

    def segments_at_ref(self, ref: str) -> list[Segment]:
        """The files ``confiture build`` would select at *ref*, in build order, with their text.

        Each segment names the file where it sits in the repository — the path
        the working tree's build gives it — although it was read from the ref.

        Raises:
            NotAGitRepositoryError: If not in a git repository.
            GitError: The ref names no tree, git failed, or the tree holds
                something ``GitRepository.materialise`` refuses.
        """
        root = self.git_repo.get_repo_root().resolve()
        include_dirs = [config["path"] for config in self.schema_builder.include_configs]
        with tempfile.TemporaryDirectory(prefix="confiture-ref-") as scratch:
            # The repository root's own name is kept: the seed rule reads it.
            tree = Path(scratch) / root.name
            tree.mkdir()
            tree = tree.resolve()
            self.git_repo.materialise(ref, include_dirs, tree)
            at_ref = SchemaBuilder(_environment_at(self.schema_builder.env_config, root, tree))
            # Reason: the ref's selection is the build's own, minus the refusal of an empty tree
            selected = at_ref._select(require_files=False)
            return selection_segments(
                [record.path for record in selected],
                root=self.repo_path,
                mapped_from=(tree, root),
            )

    def read_at_ref(self, ref: str) -> SchemaRead:
        """*ref*'s schema, read once per tree: a second ref naming the same tree is not read again."""
        tree = self.git_repo.tree_oid(ref)
        if tree not in self._reads:
            self._reads[tree] = read_segments(self.segments_at_ref(tree))
        return self._reads[tree]

    def build_schema_at_ref(self, ref: str) -> str:
        """The schema at *ref* as one text: the selected files, joined the one way.

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If git operations fail
        """
        return joined(self.segments_at_ref(ref))


class GitSchemaDiffer:
    """Compare schemas between git refs.

    Uses GitSchemaBuilder to read the schema at each ref, then SchemaDiffer to
    compare the two reads.

    Attributes:
        env: Environment name
        repo_path: The project directory
        builder: GitSchemaBuilder instance
        differ: SchemaDiffer instance

    Example:
        >>> differ = GitSchemaDiffer("local", Path("."))
        >>> diff = differ.compare_refs("origin/main", "HEAD")
        >>> has_ddl = differ.has_ddl_changes(diff)
    """

    def __init__(self, env: str, repo_path: Path | None = None):
        """Initialize GitSchemaDiffer.

        Args:
            env: Environment name (e.g., "local", "production")
            repo_path: The project directory (default: current directory)
        """
        self.env = env
        self.repo_path = repo_path or Path.cwd()
        self.builder = GitSchemaBuilder(env, self.repo_path)
        self.differ = SchemaDiffer()

    def compare_refs(self, base_ref: str, target_ref: str = "HEAD") -> SchemaDiff:
        """Compare schemas between two git refs.

        Two refs naming one tree are one schema: nothing is read. Each tree is
        read once per differ, however many checks ask.

        Args:
            base_ref: Base git reference (e.g., "origin/main")
            target_ref: Target git reference (default "HEAD"), or a tree OID

        Returns:
            SchemaDiff object with detected changes

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If git operations fail, or neither ref holds a file the
                working tree's build selects (the include directories are untracked)
            SchemaError: ``DIFFER_400`` naming the file PostgreSQL rejects
            DifferError: as ``SchemaDiffer.compare_sides``
        """
        repo = self.builder.git_repo
        base_tree, target_tree = repo.tree_oid(base_ref), repo.tree_oid(target_ref)
        if base_tree == target_tree:
            return SchemaDiff()
        base = self.builder.read_at_ref(base_tree)
        target = self.builder.read_at_ref(target_tree)
        if not base.segments and not target.segments:
            self._refuse_untracked(base_ref, target_ref)
        return self.differ.compare_reads(base, target)

    def _refuse_untracked(self, base_ref: str, target_ref: str) -> None:
        """Refuse two empty refs when the working tree's build selects files: they are untracked."""
        # Reason: the working tree's selection, asked whether it is empty, not refused for it
        if not self.builder.schema_builder._select(require_files=False):
            return
        raise GitError(
            f"The include directories are not tracked at either ref ({base_ref}, {target_ref}): "
            "the working tree's build selects files neither ref holds",
            resolution_hint="Commit (or stage, with --staged) the include directories.",
        )

    def has_ddl_changes(self, diff: SchemaDiff) -> bool:
        """Check if diff has meaningful DDL changes (not just whitespace).

        Args:
            diff: SchemaDiff object to analyze

        Returns:
            True if there are structural schema changes, False if only whitespace/comments

        Example:
            >>> differ = GitSchemaDiffer("local")
            >>> diff = differ.compare_refs("HEAD~1", "HEAD")
            >>> if differ.has_ddl_changes(diff):
            ...     print("Schema has changed")
        """
        # If SchemaDiffer found changes, they are structural changes
        # (not just whitespace, since it parses SQL)
        return diff.has_changes()
