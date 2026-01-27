"""Migration file checksum computation and verification.

Provides SHA-256 checksum computation and verification for migration files
to detect unauthorized modifications after migrations are applied.

This helps prevent:
- Silent schema drift between environments
- Production/staging mismatches
- Debugging nightmares from modified migrations
"""

import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg

logger = logging.getLogger(__name__)


class ChecksumMismatchBehavior(Enum):
    """Behavior when checksum mismatch is detected."""

    FAIL = "fail"  # Raise error, stop migrations
    WARN = "warn"  # Log warning, continue
    IGNORE = "ignore"  # Silently continue


@dataclass
class ChecksumConfig:
    """Configuration for checksum verification.

    Attributes:
        enabled: Whether checksum verification is enabled (default: True)
        on_mismatch: Behavior when mismatch detected (default: FAIL)
        algorithm: Hash algorithm to use (default: sha256)

    Example:
        >>> config = ChecksumConfig(on_mismatch=ChecksumMismatchBehavior.WARN)
        >>> config = ChecksumConfig(enabled=False)  # Disable verification
    """

    enabled: bool = True
    on_mismatch: ChecksumMismatchBehavior = field(default=ChecksumMismatchBehavior.FAIL)
    algorithm: str = "sha256"


@dataclass
class ChecksumMismatch:
    """Record of a checksum mismatch.

    Attributes:
        version: Migration version
        name: Migration name
        file_path: Path to migration file
        expected: Expected checksum (stored in database)
        actual: Actual checksum (computed from file)
    """

    version: str
    name: str
    file_path: Path
    expected: str
    actual: str


class ChecksumVerificationError(Exception):
    """Raised when checksum verification fails.

    Attributes:
        mismatches: List of ChecksumMismatch objects
    """

    def __init__(self, mismatches: list[ChecksumMismatch]):
        self.mismatches = mismatches
        files = ", ".join(m.version for m in mismatches)
        super().__init__(
            f"Checksum verification failed for {len(mismatches)} migration(s): {files}. "
            "Migration files have been modified after application. "
            "This can cause schema drift between environments."
        )


def compute_checksum(file_path: Path, algorithm: str = "sha256") -> str:
    """Compute checksum of a migration file.

    Args:
        file_path: Path to migration file
        algorithm: Hash algorithm (default: sha256)

    Returns:
        Hex-encoded checksum string (64 characters for SHA-256)

    Example:
        >>> checksum = compute_checksum(Path("001_create_users.py"))
        >>> print(checksum)
        "a3f2b8c9d4e5f6a1b2c3d4e5f6a7b8c9..."
    """
    hasher = hashlib.new(algorithm)

    with open(file_path, "rb") as f:
        # Read in chunks for memory efficiency with large files
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)

    return hasher.hexdigest()


def compute_checksum_from_content(content: str | bytes, algorithm: str = "sha256") -> str:
    """Compute checksum from content directly.

    Useful for computing checksums without writing to disk.

    Args:
        content: File content as string or bytes
        algorithm: Hash algorithm (default: sha256)

    Returns:
        Hex-encoded checksum string

    Example:
        >>> checksum = compute_checksum_from_content("def up(): pass")
        >>> print(len(checksum))
        64
    """
    hasher = hashlib.new(algorithm)

    if isinstance(content, str):
        content = content.encode("utf-8")

    hasher.update(content)
    return hasher.hexdigest()


class MigrationChecksumVerifier:
    """Verifies migration file integrity against stored checksums.

    Compares the SHA-256 checksums of migration files on disk against
    the checksums that were stored when the migrations were applied.

    Example:
        >>> import psycopg
        >>> conn = psycopg.connect("postgresql://localhost/mydb")
        >>> verifier = MigrationChecksumVerifier(conn)
        >>> mismatches = verifier.verify_all(Path("db/migrations"))
        >>> if mismatches:
        ...     print(f"Found {len(mismatches)} modified migrations!")

        >>> # With custom config
        >>> config = ChecksumConfig(on_mismatch=ChecksumMismatchBehavior.WARN)
        >>> verifier = MigrationChecksumVerifier(conn, config)
        >>> verifier.verify_all(Path("db/migrations"))  # Logs warnings instead of raising
    """

    def __init__(
        self,
        connection: "psycopg.Connection",
        config: ChecksumConfig | None = None,
    ):
        """Initialize verifier.

        Args:
            connection: psycopg3 database connection
            config: Checksum configuration (uses defaults if None)
        """
        self.connection = connection
        self.config = config or ChecksumConfig()

    def verify_all(self, migrations_dir: Path) -> list[ChecksumMismatch]:
        """Verify all applied migrations against their stored checksums.

        Args:
            migrations_dir: Directory containing migration files

        Returns:
            List of mismatches (empty if all match)

        Raises:
            ChecksumVerificationError: If mismatches found and behavior is FAIL
        """
        if not self.config.enabled:
            logger.debug("Checksum verification disabled")
            return []

        # Get stored checksums from database
        stored = self._get_stored_checksums()

        if not stored:
            logger.debug("No stored checksums to verify")
            return []

        mismatches = []

        for version, (name, expected_checksum) in stored.items():
            # Find migration file
            file_path = self._find_migration_file(migrations_dir, version, name)

            if file_path is None:
                logger.warning(f"Migration file not found for {version}_{name}")
                continue

            # Compute current checksum
            actual_checksum = compute_checksum(file_path, self.config.algorithm)

            # Missing checksum is treated as mismatch
            if expected_checksum is None or actual_checksum != expected_checksum:
                mismatches.append(
                    ChecksumMismatch(
                        version=version,
                        name=name,
                        file_path=file_path,
                        expected=expected_checksum,
                        actual=actual_checksum,
                    )
                )

        # Handle mismatches based on config
        if mismatches:
            self._handle_mismatches(mismatches)

        return mismatches

    def verify_single(self, migration_file: Path, expected_checksum: str) -> bool:
        """Verify a single migration file against expected checksum.

        Args:
            migration_file: Path to migration file
            expected_checksum: Expected checksum value

        Returns:
            True if checksums match, False otherwise
        """
        if not self.config.enabled:
            return True

        actual = compute_checksum(migration_file, self.config.algorithm)
        return actual == expected_checksum

    def _get_stored_checksums(self) -> dict[str, tuple[str, str | None]]:
        """Get stored checksums from database.

        Returns:
            Dict mapping version -> (name, checksum)
        """
        with self.connection.cursor() as cur:
            cur.execute("""
                SELECT version, name, checksum
                FROM tb_confiture
                ORDER BY version
            """)
            return {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    def _find_migration_file(
        self,
        migrations_dir: Path,
        version: str,
        name: str,
    ) -> Path | None:
        """Find migration file by version and name.

        Args:
            migrations_dir: Directory to search
            version: Migration version
            name: Migration name

        Returns:
            Path to migration file, or None if not found
        """
        # Try exact match first
        exact_path = migrations_dir / f"{version}_{name}.py"
        if exact_path.exists():
            return exact_path

        # Try pattern match (in case name has slight differences)
        for f in migrations_dir.glob(f"{version}_*.py"):
            return f

        return None

    def _handle_mismatches(self, mismatches: list[ChecksumMismatch]) -> None:
        """Handle checksum mismatches based on configuration.

        Args:
            mismatches: List of detected mismatches

        Raises:
            ChecksumVerificationError: If behavior is FAIL
        """
        behavior = self.config.on_mismatch

        if behavior == ChecksumMismatchBehavior.IGNORE:
            return

        # Build message
        msg_lines = ["Checksum verification found modified migrations:"]
        for m in mismatches:
            msg_lines.append(
                f"  - {m.version}_{m.name}: expected {m.expected[:12]}..., got {m.actual[:12]}..."
            )

        message = "\n".join(msg_lines)

        if behavior == ChecksumMismatchBehavior.WARN:
            logger.warning(message)
        elif behavior == ChecksumMismatchBehavior.FAIL:
            raise ChecksumVerificationError(mismatches)

    def update_checksum(self, version: str, new_checksum: str) -> None:
        """Update stored checksum for a migration.

        Use with caution - this should only be used when you're certain
        the file modification was intentional.

        Args:
            version: Migration version
            new_checksum: New checksum value
        """
        with self.connection.cursor() as cur:
            cur.execute(
                """
                UPDATE tb_confiture
                SET checksum = %s
                WHERE version = %s
            """,
                (new_checksum, version),
            )
        self.connection.commit()
        logger.info(f"Updated checksum for migration {version}")

    def update_all_checksums(self, migrations_dir: Path) -> int:
        """Update all stored checksums from current files.

        WARNING: This should only be used when you're certain all
        file modifications were intentional.

        Args:
            migrations_dir: Directory containing migration files

        Returns:
            Number of checksums updated
        """
        stored = self._get_stored_checksums()
        updated = 0

        for version, (name, _) in stored.items():
            file_path = self._find_migration_file(migrations_dir, version, name)
            if file_path is None:
                continue

            new_checksum = compute_checksum(file_path, self.config.algorithm)
            self.update_checksum(version, new_checksum)
            updated += 1

        return updated
