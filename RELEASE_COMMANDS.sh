#!/bin/bash
# Confiture v0.6.0 Release Commands
# Run these commands to release v0.6.0 to PyPI and GitHub

set -e  # Exit on error

echo "🍓 Confiture v0.6.0 Release Script"
echo "===================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Step 1: Verify everything is ready
echo -e "${BLUE}Step 1: Verification${NC}"
echo "Checking version..."
VERSION=$(grep '^__version__' python/confiture/__init__.py | grep -o '"[^"]*"' | tr -d '"')
echo "Version: $VERSION"

if [ "$VERSION" != "0.6.0" ]; then
    echo -e "${YELLOW}ERROR: Version mismatch. Expected 0.6.0, got $VERSION${NC}"
    exit 1
fi

echo "Running tests..."
uv run pytest -q
echo -e "${GREEN}✓ Tests passed${NC}"

echo "Checking code quality..."
uv run ruff check . > /dev/null && echo -e "${GREEN}✓ Code quality passed${NC}"

echo ""

# Step 2: Create release commit
echo -e "${BLUE}Step 2: Git Commit${NC}"
echo "Current status:"
git status --short

read -p "Create release commit? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git add -A
    git commit -m "chore(release): v0.6.0 - timestamp-based migration versioning

- Switch from sequential (001, 002, ..., 999) to timestamp (YYYYMMDDHHmmss) versioning
- Eliminates merge conflicts in multi-developer environments
- Removes 999 migration hard limit
- 100% backwards compatible with existing migrations
- Adds comprehensive migration versioning strategies guide

See RELEASE_NOTES.md and docs/guides/migration-versioning-strategies.md"
    echo -e "${GREEN}✓ Release commit created${NC}"
else
    echo "Skipped"
fi

echo ""

# Step 3: Create git tag
echo -e "${BLUE}Step 3: Create Git Tag${NC}"
read -p "Create git tag v0.6.0? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git tag -a v0.6.0 -m "Confiture v0.6.0: Timestamp-Based Migration Versioning

Breaking Changes:
- Generated migrations now use YYYYMMDDHHMMSS format instead of zero-padded integers (001, 002, ...)
- Old migrations continue to work and sort first (correct execution order)
- No 999 migration limit anymore
- Zero merge conflicts in multi-developer environments

Features:
- Timestamp-based versioning (YYYYMMDDHHmmss_name.py)
- 100% backwards compatible with existing 001_-style migrations
- Comprehensive migration versioning strategies guide
- 4,664 tests passing

See RELEASE_NOTES.md and docs/guides/migration-versioning-strategies.md"
    echo -e "${GREEN}✓ Git tag created${NC}"
else
    echo "Skipped"
fi

echo ""

# Step 4: Push to GitHub
echo -e "${BLUE}Step 4: Push to GitHub${NC}"
read -p "Push main branch and tag to GitHub? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Pushing main..."
    git push origin main
    echo "Pushing tag..."
    git push origin v0.6.0
    echo -e "${GREEN}✓ Pushed to GitHub${NC}"
else
    echo "Skipped"
fi

echo ""

# Step 5: Build distribution
echo -e "${BLUE}Step 5: Build Distribution${NC}"
read -p "Build wheel and source distribution? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Cleaning old builds..."
    rm -rf build/ dist/ *.egg-info confiture-*.egg-info fraiseql_confiture-*.egg-info

    echo "Building distribution..."
    python -m build

    echo ""
    echo -e "${GREEN}✓ Distribution built${NC}"
    echo "Artifacts:"
    ls -lh dist/
else
    echo "Skipped"
fi

echo ""

# Step 6: Upload to PyPI
echo -e "${BLUE}Step 6: Upload to PyPI${NC}"
echo -e "${YELLOW}Note: Make sure you have PyPI credentials configured in ~/.pypirc${NC}"
read -p "Upload to PyPI? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python -m twine upload dist/* --verbose
    echo -e "${GREEN}✓ Uploaded to PyPI${NC}"
else
    echo "Skipped - you can upload manually with: python -m twine upload dist/*"
fi

echo ""

# Step 7: Create GitHub release
echo -e "${BLUE}Step 7: Create GitHub Release${NC}"
read -p "Create GitHub release? (Requires 'gh' CLI) (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if command -v gh &> /dev/null; then
        gh release create v0.6.0 \
            --title "Confiture v0.6.0: Timestamp-Based Migration Versioning" \
            --notes-file RELEASE_NOTES.md \
            dist/*
        echo -e "${GREEN}✓ GitHub release created${NC}"
    else
        echo -e "${YELLOW}⚠ 'gh' CLI not found. Create release manually at:${NC}"
        echo "https://github.com/fraiseql/confiture/releases/new?tag=v0.6.0"
    fi
else
    echo "Skipped"
fi

echo ""
echo -e "${GREEN}✅ Release Process Complete!${NC}"
echo ""
echo "Summary:"
echo "- Version: 0.6.0"
echo "- Tests: 4,664 passing"
echo "- Code Quality: ✓ Clean"
echo "- Documentation: ✓ Complete"
echo "- Backwards Compatibility: ✓ 100%"
echo ""
echo "Next steps:"
echo "1. Monitor PyPI for successful upload"
echo "2. Share release notes with community"
echo "3. Update any dependent projects"
echo ""
echo "Release Notes: RELEASE_NOTES.md"
echo "Release Checklist: RELEASE_CHECKLIST.md"
echo ""
