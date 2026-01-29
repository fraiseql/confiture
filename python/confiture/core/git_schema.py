"""Schema building and comparison from git refs.

Extends SchemaBuilder and SchemaDiffer to work with git history.
Enables schema validation against git refs for drift detection.
"""

from pathlib import Path
from typing import Any

from confiture.core.builder import SchemaBuilder
from confiture.core.differ import SchemaDiffer
from confiture.core.git import GitRepository
from confiture.models.schema import SchemaDiff


class GitSchemaBuilder:
    """Build schema from files at a specific git ref.

    Retrieves all schema files from a git ref and concatenates them
    using SchemaBuilder logic, enabling schema comparison across commits.

    Attributes:
        env: Environment name
        repo_path: Repository root directory
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
            repo_path: Repository root directory (default: current directory)
        """
        self.env = env
        self.repo_path = repo_path or Path.cwd()
        self.git_repo = GitRepository(self.repo_path)

        # Load schema builder config to understand file structure
        self.schema_builder = SchemaBuilder(env, self.repo_path)

    def build_schema_at_ref(self, ref: str) -> str:
        """Build complete schema by retrieving files from git ref.

        Reconstructs the schema at a specific point in git history by:
        1. Discovering schema files (using current env config)
        2. Retrieving file content from the given ref
        3. Concatenating in deterministic order

        Args:
            ref: Git reference (commit, branch, tag, etc.)

        Returns:
            Complete schema SQL as string (may be empty)

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If git operations fail
            ConfigurationError: If schema configuration is invalid

        Example:
            >>> builder = GitSchemaBuilder("local")
            >>> schema_v1 = builder.build_schema_at_ref("v1.0.0")
            >>> schema_main = builder.build_schema_at_ref("origin/main")
        """
        # Use SchemaBuilder's include configs to find files
        # but retrieve from git ref instead of filesystem

        schema_parts: list[str] = []

        # Process each include config in order
        for include_config in self.schema_builder.include_configs:
            schema_parts.extend(self._build_from_include_at_ref(ref, include_config))

        return "\n".join(schema_parts)

    def _build_from_include_at_ref(self, ref: str, include_config: dict[str, Any]) -> list[str]:
        """Build schema from single include path at ref.

        Discovers files matching include patterns and retrieves from git.

        Args:
            ref: Git reference (commit hash, branch name, tag, etc.)
            include_config: Include directory configuration dict with keys:
                - path: Directory path (e.g., "db/schema")
                - recursive: Whether to search recursively (bool)
                - include: Include patterns (list[str])
                - exclude: Exclude patterns (list[str])

        Returns:
            List of file contents in deterministic (alphabetical) order
        """
        include_path = include_config["path"]
        recursive = include_config["recursive"]

        # Use git ls-tree to discover files at ref
        schema_parts: list[str] = []

        # We need to list files at the ref, but git doesn't provide
        # easy pattern matching. For now, we'll use a practical approach:
        # Temporarily write files from git to temp dir and scan them
        # This is more robust than trying to parse git ls-tree output

        # Get list of SQL files from filesystem at ref
        files = self._get_files_at_ref(ref, include_path, recursive)

        # Retrieve content for each file and sort
        file_contents: list[tuple[Path, str]] = []
        for file_path in files:
            content = self.git_repo.get_file_at_ref(file_path, ref)
            if content is not None:
                file_contents.append((file_path, content))

        # Sort by path for deterministic order
        file_contents.sort(key=lambda x: x[0])

        # Concatenate contents
        for _, content in file_contents:
            schema_parts.append(content)

        return schema_parts

    def _get_files_at_ref(self, ref: str, directory: Path, recursive: bool) -> list[Path]:
        """Get list of SQL files at ref in directory.

        Uses git ls-tree to list files without fetching them all.

        Args:
            ref: Git reference
            directory: Directory to search
            recursive: Whether to search recursively

        Returns:
            List of SQL file paths

        Raises:
            GitError: If git command fails
        """
        import subprocess

        from confiture.exceptions import GitError

        # Build git command
        cmd = ["git", "ls-tree", ref, "--", directory.as_posix()]
        if recursive:
            cmd.insert(2, "-r")

        # Use git ls-tree to list files
        try:
            result = subprocess.run(
                cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as e:
            raise GitError(f"Git command timed out listing files at '{ref}': {e}") from e

        if result.returncode != 0:
            raise GitError(f"Failed to list files at '{ref}': {result.stderr.strip()}")

        files: list[Path] = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            # Parse ls-tree output: mode type hash path
            parts = line.split("\t")
            if len(parts) == 2:
                path_str = parts[1]
                path = Path(path_str)
                if path.suffix == ".sql":
                    files.append(path)

        return files


class GitSchemaDiffer:
    """Compare schemas between git refs.

    Uses GitSchemaBuilder to reconstruct schemas at different refs,
    then uses SchemaDiffer to detect changes.

    Attributes:
        env: Environment name
        repo_path: Repository root directory
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
            repo_path: Repository root directory (default: current directory)
        """
        self.env = env
        self.repo_path = repo_path or Path.cwd()
        self.builder = GitSchemaBuilder(env, self.repo_path)
        self.differ = SchemaDiffer()

    def compare_refs(self, base_ref: str, target_ref: str = "HEAD") -> SchemaDiff:
        """Compare schemas between two git refs.

        Args:
            base_ref: Base git reference (e.g., "origin/main")
            target_ref: Target git reference (default "HEAD")

        Returns:
            SchemaDiff object with detected changes

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If git operations fail

        Example:
            >>> differ = GitSchemaDiffer("local")
            >>> diff = differ.compare_refs("origin/main", "HEAD")
            >>> print(f"Found {len(diff.changes)} changes")
        """
        # Build schemas at both refs
        base_schema = self.builder.build_schema_at_ref(base_ref)
        target_schema = self.builder.build_schema_at_ref(target_ref)

        # Compare using existing SchemaDiffer
        return self.differ.compare(base_schema, target_schema)

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
