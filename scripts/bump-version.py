#!/usr/bin/env python3
"""
Version bumping script for Confiture.

Updates all version references across the project:
- pyproject.toml
- python/confiture/__init__.py
- python/confiture/cli/main.py
- CLAUDE.md
- CHANGELOG.md

Usage:
    python scripts/bump-version.py 0.3.13
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path


def bump_version(new_version: str) -> None:
    """Bump version to new_version across all files."""
    root = Path(__file__).parent.parent

    # Validate version format
    if not re.match(r"^\d+\.\d+\.\d+$", new_version):
        print(f"❌ Invalid version format: {new_version}")
        print("Expected format: X.Y.Z (e.g., 0.3.13)")
        sys.exit(1)

    print(f"🔄 Bumping version to {new_version}")
    print("=" * 50)

    files_updated = 0

    # 1. Update pyproject.toml
    pyproject = root / "pyproject.toml"
    content = pyproject.read_text()
    original = content
    content = re.sub(
        r'version = "\d+\.\d+\.\d+"',
        f'version = "{new_version}"',
        content,
    )
    if content != original:
        pyproject.write_text(content)
        print(f"✅ Updated {pyproject.relative_to(root)}")
        files_updated += 1
    else:
        print(f"⏭️  No changes needed in {pyproject.relative_to(root)}")

    # 2. Update python/confiture/__init__.py
    init_file = root / "python" / "confiture" / "__init__.py"
    content = init_file.read_text()
    original = content
    content = re.sub(
        r'__version__ = "\d+\.\d+\.\d+"',
        f'__version__ = "{new_version}"',
        content,
    )
    if content != original:
        init_file.write_text(content)
        print(f"✅ Updated {init_file.relative_to(root)}")
        files_updated += 1
    else:
        print(f"⏭️  No changes needed in {init_file.relative_to(root)}")

    # 3. Update python/confiture/cli/main.py
    cli_file = root / "python" / "confiture" / "cli" / "main.py"
    content = cli_file.read_text()
    original = content
    content = re.sub(
        r'__version__ = "\d+\.\d+\.\d+"',
        f'__version__ = "{new_version}"',
        content,
    )
    if content != original:
        cli_file.write_text(content)
        print(f"✅ Updated {cli_file.relative_to(root)}")
        files_updated += 1
    else:
        print(f"⏭️  No changes needed in {cli_file.relative_to(root)}")

    # 4. Update CLAUDE.md
    claude_file = root / "CLAUDE.md"
    content = claude_file.read_text()
    original = content

    # Update version line
    content = re.sub(
        r"\*\*Version\*\*: \d+\.\d+\.\d+",
        f"**Version**: {new_version}",
        content,
    )

    # Update status line if current version mentioned
    current_date = datetime.now().strftime("%B %d, %Y")
    content = re.sub(
        r"(\*\*Last Updated\*\*): .*",
        f"\\1: {current_date}",
        content,
    )

    if content != original:
        claude_file.write_text(content)
        print(f"✅ Updated {claude_file.relative_to(root)}")
        files_updated += 1
    else:
        print(f"⏭️  No changes needed in {claude_file.relative_to(root)}")

    # 5. Update CHANGELOG.md
    changelog = root / "CHANGELOG.md"
    content = changelog.read_text()
    original = content

    # Check if unreleased section exists
    if "## [Unreleased]" in content:
        # Replace [Unreleased] with version and date
        today = datetime.now().strftime("%Y-%m-%d")
        content = content.replace(
            "## [Unreleased]",
            f"## [{new_version}] - {today}\n\n## [Unreleased]",
        )

        if content != original:
            changelog.write_text(content)
            print(f"✅ Updated {changelog.relative_to(root)}")
            files_updated += 1
        else:
            print(f"⏭️  No changes needed in {changelog.relative_to(root)}")
    else:
        print(f"⏭️  No [Unreleased] section in {changelog.relative_to(root)}")

    print()
    print("=" * 50)
    if files_updated > 0:
        print(f"✅ Successfully updated {files_updated} file(s) to version {new_version}")
        print()
        print("Next steps:")
        print("  1. Review changes: git diff")
        print(f"  2. Commit: git commit -m 'chore: bump version to {new_version}'")
        print(f"  3. Tag: git tag v{new_version}")
        print("  4. Push: git push && git push --tags")
    else:
        print("❌ No files were updated")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/bump-version.py <new_version>")
        print("Example: python scripts/bump-version.py 0.3.13")
        sys.exit(1)

    bump_version(sys.argv[1])
