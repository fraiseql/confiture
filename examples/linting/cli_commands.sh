#!/bin/bash
# Common confiture lint commands
#
# This script demonstrates the most common CLI commands for schema linting.
# Each command shows a different use case.
#
# Run individual commands to see their output, or source this file to load
# all commands into your shell for quick access.

# ============================================================================
# BASIC LINTING
# ============================================================================

# Lint the default (local) environment
# Output: Rich table format with colors
basic_lint() {
    confiture lint
}

# ============================================================================
# ENVIRONMENT-SPECIFIC LINTING
# ============================================================================

# Lint development environment
dev_lint() {
    confiture lint --env development
}

# Lint staging environment
staging_lint() {
    confiture lint --env staging
}

# Lint production environment (strict mode)
prod_lint() {
    confiture lint --env production --fail-on-warning
}

# ============================================================================
# OUTPUT FORMATS
# ============================================================================

# Output as JSON (useful for parsing in scripts)
json_output() {
    confiture lint --format json
}

# Output as CSV (useful for spreadsheet analysis)
csv_output() {
    confiture lint --format csv
}

# Output as table (default, human-readable)
table_output() {
    confiture lint --format table
}

# ============================================================================
# SAVING REPORTS
# ============================================================================

# Save JSON report to file
save_json_report() {
    confiture lint --format json --output lint-report.json
    echo "Report saved to lint-report.json"
}

# Save CSV report to file (with timestamp)
save_csv_report() {
    TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
    confiture lint --format csv --output "lint-report-$TIMESTAMP.csv"
    echo "Report saved to lint-report-$TIMESTAMP.csv"
}

# ============================================================================
# FAIL MODES
# ============================================================================

# Strict mode: fail on both errors and warnings
strict_mode() {
    confiture lint --fail-on-error --fail-on-warning
}

# Relaxed mode: only fail on errors, ignore warnings
errors_only() {
    confiture lint --fail-on-error --no-fail-on-warning
}

# Very relaxed: don't fail on errors (just report)
report_only() {
    confiture lint --no-fail-on-error
}

# ============================================================================
# COMBINED COMMANDS
# ============================================================================

# Generate JSON report for production (strict, saved)
prod_report() {
    confiture lint --env production --format json \
        --output prod-lint-report.json \
        --fail-on-error --fail-on-warning
    echo "Production lint report generated"
}

# Check for security violations only
security_check() {
    confiture lint --format json | \
        grep -i "security" || echo "No security violations found"
}

# Check for index violations
index_check() {
    confiture lint --format json | \
        grep -i "missing.*index" || echo "All indexes present"
}

# ============================================================================
# CI/CD INTEGRATION
# ============================================================================

# Pre-commit hook: lint before allowing commit
pre_commit_check() {
    echo "Checking schema before commit..."
    if confiture lint --env local --fail-on-error; then
        echo "✅ Schema check passed"
        return 0
    else
        echo "❌ Schema has errors. Fix them before committing."
        return 1
    fi
}

# CI/CD pipeline check: strict mode with reporting
ci_check() {
    echo "Running CI schema checks..."

    # Generate report
    confiture lint --format json --output ci-lint-report.json \
        --env staging --fail-on-error --fail-on-warning

    exit_code=$?

    if [ $exit_code -eq 0 ]; then
        echo "✅ CI lint checks passed"
    else
        echo "❌ CI lint checks failed"
        echo "Report saved to ci-lint-report.json"
    fi

    return $exit_code
}

# ============================================================================
# ANALYSIS COMMANDS
# ============================================================================

# Count violations by severity
count_violations() {
    echo "Counting violations by severity..."
    confiture lint --format json | jq '.violations | {
        total: .total,
        errors: .errors,
        warnings: .warnings,
        info: .info
    }'
}

# List all violations with suggested fixes
list_with_fixes() {
    confiture lint --format json | jq '.violations.items[] | {
        rule: .rule,
        severity: .severity,
        location: .location,
        message: .message,
        fix: .suggested_fix
    }'
}

# Show only errors
show_errors_only() {
    confiture lint --format json | jq '.violations.items[] |
        select(.severity == "error") | {
        location: .location,
        message: .message,
        fix: .suggested_fix
    }'
}

# ============================================================================
# COMPARISON COMMANDS
# ============================================================================

# Compare dev and production linting results
compare_environments() {
    echo "Comparing development and production schemas..."

    echo "Development violations:"
    confiture lint --env development --format json | \
        jq '.violations.total'

    echo "Production violations:"
    confiture lint --env production --format json | \
        jq '.violations.total'
}

# ============================================================================
# HELP
# ============================================================================

# Show confiture lint help
show_help() {
    confiture lint --help
}

# Show all available commands from this script
show_commands() {
    echo "Available linting commands:"
    echo ""
    echo "Basic:"
    echo "  basic_lint          - Lint default environment"
    echo ""
    echo "Environment-specific:"
    echo "  dev_lint            - Lint development"
    echo "  staging_lint        - Lint staging"
    echo "  prod_lint           - Lint production (strict)"
    echo ""
    echo "Output formats:"
    echo "  json_output         - Output as JSON"
    echo "  csv_output          - Output as CSV"
    echo "  table_output        - Output as table"
    echo ""
    echo "Saving reports:"
    echo "  save_json_report    - Save JSON report"
    echo "  save_csv_report     - Save CSV report with timestamp"
    echo ""
    echo "Fail modes:"
    echo "  strict_mode         - Fail on errors and warnings"
    echo "  errors_only         - Fail on errors only"
    echo "  report_only         - Don't fail, just report"
    echo ""
    echo "Combined:"
    echo "  prod_report         - Production report (strict, saved)"
    echo "  security_check      - Check for security violations"
    echo "  index_check         - Check for index violations"
    echo ""
    echo "CI/CD:"
    echo "  pre_commit_check    - Pre-commit hook"
    echo "  ci_check            - CI pipeline check"
    echo ""
    echo "Analysis:"
    echo "  count_violations    - Count violations by severity"
    echo "  list_with_fixes     - List all violations with fixes"
    echo "  show_errors_only    - Show only errors"
    echo ""
    echo "Comparison:"
    echo "  compare_environments - Compare dev vs production"
    echo ""
    echo "Help:"
    echo "  show_help           - Show confiture lint help"
    echo "  show_commands       - Show this list"
}

# ============================================================================
# DEFAULT: Show usage
# ============================================================================

if [ "$1" == "--help" ] || [ "$1" == "-h" ]; then
    show_commands
    exit 0
fi

if [ -z "$1" ]; then
    echo "Schema Linting Commands"
    echo ""
    echo "Usage: source cli_commands.sh"
    echo "       Then run: basic_lint, dev_lint, etc."
    echo ""
    echo "Or run individual commands directly:"
    echo "  bash cli_commands.sh basic_lint"
    echo "  bash cli_commands.sh dev_lint"
    echo "  bash cli_commands.sh show_commands"
    echo ""
    show_commands
    exit 0
fi

# If called with a function name, execute it
if declare -f "$1" > /dev/null; then
    "$@"
else
    echo "Error: Command '$1' not found"
    show_commands
    exit 1
fi
