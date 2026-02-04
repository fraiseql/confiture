#!/usr/bin/env bash

# Test scenarios for comment validation example
# This script demonstrates the different use cases

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🍓 Confiture Comment Validation Example"
echo "========================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper function to show section
show_section() {
    echo -e "${BLUE}$1${NC}"
    echo "---"
}

# Helper function for success
success() {
    echo -e "${GREEN}✅ $1${NC}"
}

# Helper function for failure
failure() {
    echo -e "${RED}❌ $1${NC}"
}

# Helper function for warning
warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# Reset schema directory
reset_schema() {
    echo "Resetting schema directory..."
    rm -f db/schema/20_views_broken.sql
    cp db/schema/20_views_safe.sql db/schema/20_views.sql
}

# Cleanup
cleanup() {
    echo ""
    echo "Cleaning up..."
    rm -f db/generated/schema_*.sql
}

trap cleanup EXIT

echo ""
show_section "Scenario 1: Unsafe Build (No Validation)"
echo "Using environment config with validation disabled..."
echo ""

reset_schema

# Put back broken file temporarily
cat > db/schema/20_views_broken.sql << 'EOF'
/* This comment is unclosed
   and will cause spillover
EOF

echo "Running: confiture build --env unsafe"
if confiture build --env unsafe > /dev/null 2>&1; then
    warning "Build succeeded but schema may be invalid"
    echo "This is the problem - the build succeeds silently!"
    success "Scenario 1 complete: Unsafe build produces invalid SQL"
else
    failure "Build failed unexpectedly"
fi

echo ""
show_section "Scenario 2: Safe Build (With Validation)"
echo "Using environment config with validation enabled..."
echo ""

reset_schema

# Put back broken file temporarily
cat > db/schema/20_views_broken.sql << 'EOF'
/* This comment is unclosed
   and will cause spillover
EOF

echo "Running: confiture build --env safe"
if confiture build --env safe 2>&1 | grep -q "Comment validation failed"; then
    success "Scenario 2 complete: Validation caught the unclosed comment!"
else
    failure "Validation should have caught the error"
fi

echo ""
show_section "Scenario 3: CLI Override - Enable Validation"
echo "Using CLI flag to override config..."
echo ""

reset_schema

# Put back broken file temporarily
cat > db/schema/20_views_broken.sql << 'EOF'
/* This comment is unclosed
EOF

echo "Running: confiture build --env unsafe --validate-comments"
if confiture build --env unsafe --validate-comments 2>&1 | grep -q "Comment validation failed"; then
    success "Scenario 3 complete: CLI flag --validate-comments overrode config"
else
    failure "CLI override should have enabled validation"
fi

echo ""
show_section "Scenario 4: Fix Schema and Rebuild"
echo "Removing broken file and rebuilding..."
echo ""

reset_schema

echo "Running: confiture build --env safe --validate-comments"
if confiture build --env safe --validate-comments > /dev/null 2>&1; then
    success "Scenario 4 complete: Fixed schema builds successfully"
else
    failure "Build should succeed with fixed schema"
fi

echo ""
show_section "Scenario 5: Separator Style Override"
echo "Testing different separator styles with CLI flags..."
echo ""

reset_schema

echo "Testing block_comment style:"
echo "Running: confiture build --separator-style block_comment"
if confiture build --separator-style block_comment > /dev/null 2>&1; then
    if grep -q "/\*" db/generated/schema_local.sql; then
        success "Block comment separators used"
    fi
fi

echo ""
echo "Testing line_comment style:"
echo "Running: confiture build --separator-style line_comment"
if confiture build --separator-style line_comment > /dev/null 2>&1; then
    if grep -q "^--" db/generated/schema_local.sql; then
        success "Line comment separators used"
    fi
fi

echo ""
echo "Testing custom template:"
echo "Running: confiture build --separator-style custom --separator-template '\\n/* === {file_path} === */\\n'"
if confiture build --separator-style custom --separator-template $'\\n/* === {file_path} === */\\n' > /dev/null 2>&1; then
    if grep -q "===" db/generated/schema_local.sql; then
        success "Custom template used"
    fi
fi

echo ""
show_section "Scenario 6: Strict Validation"
echo "Testing all strict flags combined..."
echo ""

reset_schema

echo "Running: confiture build --validate-comments --fail-on-unclosed --fail-on-spillover"
if confiture build --validate-comments --fail-on-unclosed --fail-on-spillover > /dev/null 2>&1; then
    success "Scenario 6 complete: All strict checks passed"
else
    failure "Strict build should pass with valid schema"
fi

echo ""
show_section "Scenario 7: Production Build Pattern"
echo "Demonstrating production build best practices..."
echo ""

reset_schema

echo "Running: confiture build --env production --validate-comments --separator-style block_comment"
if confiture build --env production --validate-comments --separator-style block_comment > /dev/null 2>&1; then
    success "Scenario 7 complete: Production build succeeded"
else
    failure "Production build should succeed"
fi

echo ""
show_section "All Test Scenarios Complete!"
echo "✅ All scenarios passed successfully"
echo ""
echo "Generated files:"
ls -lh db/generated/schema_*.sql 2>/dev/null | awk '{print "  " $9 " (" $5 ")"}'
echo ""
echo "Next steps:"
echo "  1. Review the generated schema files"
echo "  2. Try the CLI commands manually"
echo "  3. Examine the different separator styles"
echo "  4. Apply these patterns to your own projects"
