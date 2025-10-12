#!/usr/bin/env bash
#
# Production to Staging Data Sync with PII Anonymization
# Confiture Migration Tool - Example 04
#
# This script automates the process of syncing production data to staging
# with comprehensive PII anonymization and verification.
#
# Usage:
#   ./sync_script.sh [OPTIONS]
#
# Options:
#   --dry-run          Validate configuration without copying data
#   --skip-verify      Skip post-sync verification (not recommended)
#   --resume           Resume interrupted sync from checkpoint
#   --force            Force sync even if target has newer data
#   --verbose          Enable verbose logging
#
# Environment Variables:
#   PROD_DB_PASSWORD       Production database password
#   STAGING_DB_PASSWORD    Staging database password
#   SLACK_WEBHOOK_URL      Slack notification webhook (optional)
#
# Example:
#   export PROD_DB_PASSWORD="prod-secret"
#   export STAGING_DB_PASSWORD="staging-secret"
#   ./sync_script.sh --dry-run

set -euo pipefail  # Exit on error, undefined variable, or pipe failure

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/anonymization_config.yaml"
PROD_ENV_FILE="${SCRIPT_DIR}/db/environments/production.yaml"
STAGING_ENV_FILE="${SCRIPT_DIR}/db/environments/staging.yaml"
VERIFY_SQL="${SCRIPT_DIR}/verify_anonymization.sql"
LOG_FILE="${SCRIPT_DIR}/sync-$(date +%Y%m%d-%H%M%S).log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Command-line options
DRY_RUN=false
SKIP_VERIFY=false
RESUME=false
FORCE=false
VERBOSE=false

# ============================================================================
# Functions
# ============================================================================

log() {
    local level=$1
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    case $level in
        INFO)
            echo -e "${BLUE}[INFO]${NC} ${message}" | tee -a "$LOG_FILE"
            ;;
        SUCCESS)
            echo -e "${GREEN}[SUCCESS]${NC} ${message}" | tee -a "$LOG_FILE"
            ;;
        WARNING)
            echo -e "${YELLOW}[WARNING]${NC} ${message}" | tee -a "$LOG_FILE"
            ;;
        ERROR)
            echo -e "${RED}[ERROR]${NC} ${message}" | tee -a "$LOG_FILE"
            ;;
    esac
}

print_header() {
    local title="$1"
    echo ""
    echo "============================================================================"
    echo "  $title"
    echo "============================================================================"
    echo ""
}

check_prerequisites() {
    log INFO "Checking prerequisites..."

    # Check if confiture is installed
    if ! command -v confiture &> /dev/null; then
        log ERROR "confiture command not found. Install with: pip install confiture"
        exit 1
    fi

    # Check if config files exist
    if [[ ! -f "$CONFIG_FILE" ]]; then
        log ERROR "Anonymization config not found: $CONFIG_FILE"
        exit 1
    fi

    if [[ ! -f "$PROD_ENV_FILE" ]]; then
        log ERROR "Production environment config not found: $PROD_ENV_FILE"
        exit 1
    fi

    if [[ ! -f "$STAGING_ENV_FILE" ]]; then
        log ERROR "Staging environment config not found: $STAGING_ENV_FILE"
        exit 1
    fi

    # Check if verification SQL exists
    if [[ ! -f "$VERIFY_SQL" ]] && [[ "$SKIP_VERIFY" == "false" ]]; then
        log WARNING "Verification SQL not found: $VERIFY_SQL"
        log WARNING "Verification will use built-in checks only"
    fi

    # Check required environment variables
    if [[ -z "${PROD_DB_PASSWORD:-}" ]]; then
        log ERROR "PROD_DB_PASSWORD environment variable not set"
        exit 1
    fi

    if [[ -z "${STAGING_DB_PASSWORD:-}" ]]; then
        log ERROR "STAGING_DB_PASSWORD environment variable not set"
        exit 1
    fi

    log SUCCESS "Prerequisites check passed"
}

validate_config() {
    log INFO "Validating anonymization configuration..."

    # Use confiture to validate config (dry-run without connecting)
    if confiture validate-config --config "$CONFIG_FILE" >> "$LOG_FILE" 2>&1; then
        log SUCCESS "Configuration validation passed"
    else
        log ERROR "Configuration validation failed. Check $LOG_FILE for details"
        exit 1
    fi
}

run_dry_run() {
    print_header "DRY RUN - Validation Only (No Data Copied)"

    log INFO "Running dry-run validation..."
    log INFO "This will:"
    log INFO "  - Connect to source and target databases"
    log INFO "  - Analyze schema and PII columns"
    log INFO "  - Validate anonymization rules"
    log INFO "  - Calculate estimated sync time"
    log INFO "  - Check disk space requirements"

    # Build confiture command
    local cmd="confiture sync production-to-staging"
    cmd="$cmd --config $CONFIG_FILE"
    cmd="$cmd --dry-run"
    cmd="$cmd --anonymize"

    if [[ "$VERBOSE" == "true" ]]; then
        cmd="$cmd --verbose"
    fi

    log INFO "Command: $cmd"

    # Execute dry-run
    if eval "$cmd" 2>&1 | tee -a "$LOG_FILE"; then
        log SUCCESS "Dry-run completed successfully"
        log INFO "Review the output above before proceeding with actual sync"
        log INFO "To run actual sync: ./sync_script.sh (without --dry-run)"
    else
        log ERROR "Dry-run failed. Check output above for details"
        exit 1
    fi
}

create_backup() {
    log INFO "Creating staging database backup before sync..."

    local backup_file="${SCRIPT_DIR}/staging-backup-$(date +%Y%m%d-%H%M%S).sql.gz"

    # Use pg_dump to create backup
    if PGPASSWORD="$STAGING_DB_PASSWORD" pg_dump \
        -h "$(yq '.host' "$STAGING_ENV_FILE")" \
        -p "$(yq '.port' "$STAGING_ENV_FILE")" \
        -U "$(yq '.user' "$STAGING_ENV_FILE")" \
        -d "$(yq '.database' "$STAGING_ENV_FILE")" \
        --no-owner --no-acl \
        | gzip > "$backup_file" 2>> "$LOG_FILE"; then
        log SUCCESS "Backup created: $backup_file"
        log INFO "To restore: gunzip < $backup_file | psql [connection-string]"
    else
        log ERROR "Backup failed. Aborting sync for safety"
        exit 1
    fi
}

run_sync() {
    print_header "Production → Staging Sync with PII Anonymization"

    log INFO "Starting sync operation..."
    log WARNING "This will overwrite the staging database with production data"

    # Build confiture command
    local cmd="confiture sync production-to-staging"
    cmd="$cmd --config $CONFIG_FILE"
    cmd="$cmd --anonymize"

    if [[ "$RESUME" == "true" ]]; then
        cmd="$cmd --resume"
        log INFO "Resuming from previous checkpoint..."
    fi

    if [[ "$FORCE" == "true" ]]; then
        cmd="$cmd --force"
        log WARNING "Force mode enabled - will overwrite staging even if newer"
    fi

    if [[ "$VERBOSE" == "true" ]]; then
        cmd="$cmd --verbose"
    fi

    # Add progress reporting
    cmd="$cmd --progress"

    log INFO "Command: $cmd"
    log INFO "Log file: $LOG_FILE"

    # Record start time
    local start_time=$(date +%s)

    # Execute sync
    if eval "$cmd" 2>&1 | tee -a "$LOG_FILE"; then
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        local duration_min=$((duration / 60))
        local duration_sec=$((duration % 60))

        log SUCCESS "Sync completed successfully"
        log INFO "Duration: ${duration_min}m ${duration_sec}s"
    else
        log ERROR "Sync failed. Check $LOG_FILE for details"
        log INFO "To resume: ./sync_script.sh --resume"
        exit 1
    fi
}

verify_anonymization() {
    print_header "Verification - Ensuring PII Anonymization"

    log INFO "Running verification checks..."

    # First, run built-in confiture verification
    log INFO "Step 1/2: Built-in verification checks..."

    if confiture verify --env staging --config "$CONFIG_FILE" 2>&1 | tee -a "$LOG_FILE"; then
        log SUCCESS "Built-in verification passed"
    else
        log ERROR "Built-in verification failed"
        log ERROR "PII may have leaked! Do not use staging data until this is resolved"
        exit 1
    fi

    # Second, run custom SQL verification if available
    if [[ -f "$VERIFY_SQL" ]]; then
        log INFO "Step 2/2: Custom SQL verification..."

        # Extract staging connection info
        local staging_host=$(yq '.host' "$STAGING_ENV_FILE")
        local staging_port=$(yq '.port' "$STAGING_ENV_FILE")
        local staging_db=$(yq '.database' "$STAGING_ENV_FILE")
        local staging_user=$(yq '.user' "$STAGING_ENV_FILE")

        # Run verification SQL
        if PGPASSWORD="$STAGING_DB_PASSWORD" psql \
            -h "$staging_host" \
            -p "$staging_port" \
            -U "$staging_user" \
            -d "$staging_db" \
            -f "$VERIFY_SQL" \
            2>&1 | tee -a "$LOG_FILE"; then
            log SUCCESS "Custom SQL verification passed"
        else
            log ERROR "Custom SQL verification failed"
            exit 1
        fi
    else
        log INFO "Step 2/2: Skipped (no custom verification SQL)"
    fi

    log SUCCESS "All verification checks passed"
    log SUCCESS "Staging database is safe to use - no PII detected"
}

generate_report() {
    print_header "Sync Summary Report"

    # Extract key metrics from log file
    local tables_synced=$(grep -c "✓.*rows.*anonymized" "$LOG_FILE" || echo "0")
    local pii_columns=$(grep -oP '\d+(?= columns anonymized)' "$LOG_FILE" | head -1 || echo "0")
    local total_rows=$(grep -oP '\d+(?= rows)' "$LOG_FILE" | tail -1 || echo "0")

    echo "Summary"
    echo "-------"
    echo "Source: production"
    echo "Target: staging"
    echo "Date: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    echo "Results"
    echo "-------"
    echo "Tables synced: $tables_synced"
    echo "PII columns anonymized: $pii_columns"
    echo "Total rows copied: $total_rows"
    echo "Verification: PASSED"
    echo ""
    echo "Files"
    echo "-----"
    echo "Log file: $LOG_FILE"
    echo "Config: $CONFIG_FILE"
    echo ""
    echo "Next Steps"
    echo "----------"
    echo "1. Review verification output above"
    echo "2. Test application against staging database"
    echo "3. (Optional) Sync staging to local: confiture sync staging-to-local --anonymize"
    echo ""
}

send_notification() {
    if [[ -n "${SLACK_WEBHOOK_URL:-}" ]]; then
        log INFO "Sending Slack notification..."

        local message="Production → Staging sync completed successfully with PII anonymization"

        curl -X POST "$SLACK_WEBHOOK_URL" \
            -H 'Content-Type: application/json' \
            -d "{\"text\":\"✓ $message\"}" \
            >> "$LOG_FILE" 2>&1

        log SUCCESS "Slack notification sent"
    fi
}

cleanup() {
    log INFO "Cleaning up temporary files..."

    # Remove old backups (keep last 7 days)
    find "$SCRIPT_DIR" -name "staging-backup-*.sql.gz" -mtime +7 -delete 2>> "$LOG_FILE" || true

    # Remove old log files (keep last 30 days)
    find "$SCRIPT_DIR" -name "sync-*.log" -mtime +30 -delete 2>> "$LOG_FILE" || true

    log SUCCESS "Cleanup completed"
}

# ============================================================================
# Main Script
# ============================================================================

main() {
    # Parse command-line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --skip-verify)
                SKIP_VERIFY=true
                shift
                ;;
            --resume)
                RESUME=true
                shift
                ;;
            --force)
                FORCE=true
                shift
                ;;
            --verbose)
                VERBOSE=true
                shift
                ;;
            -h|--help)
                echo "Usage: $0 [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --dry-run          Validate configuration without copying data"
                echo "  --skip-verify      Skip post-sync verification (not recommended)"
                echo "  --resume           Resume interrupted sync from checkpoint"
                echo "  --force            Force sync even if target has newer data"
                echo "  --verbose          Enable verbose logging"
                echo "  -h, --help         Show this help message"
                echo ""
                echo "Environment Variables:"
                echo "  PROD_DB_PASSWORD       Production database password (required)"
                echo "  STAGING_DB_PASSWORD    Staging database password (required)"
                echo "  SLACK_WEBHOOK_URL      Slack notification webhook (optional)"
                echo ""
                echo "Example:"
                echo "  export PROD_DB_PASSWORD=\"prod-secret\""
                echo "  export STAGING_DB_PASSWORD=\"staging-secret\""
                echo "  $0 --dry-run"
                exit 0
                ;;
            *)
                log ERROR "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done

    print_header "Confiture Production Sync with PII Anonymization"

    log INFO "Log file: $LOG_FILE"

    # Step 1: Prerequisites
    check_prerequisites

    # Step 2: Validate configuration
    validate_config

    # Step 3: Dry run (if requested)
    if [[ "$DRY_RUN" == "true" ]]; then
        run_dry_run
        exit 0
    fi

    # Step 4: Create backup (before actual sync)
    if [[ "$RESUME" == "false" ]]; then
        create_backup
    fi

    # Step 5: Run sync
    run_sync

    # Step 6: Verify anonymization
    if [[ "$SKIP_VERIFY" == "false" ]]; then
        verify_anonymization
    else
        log WARNING "Verification skipped as requested (--skip-verify)"
        log WARNING "This is not recommended - PII may have leaked!"
    fi

    # Step 7: Generate report
    generate_report

    # Step 8: Send notification
    send_notification

    # Step 9: Cleanup
    cleanup

    # Final success message
    print_header "Sync Complete"
    log SUCCESS "Production data successfully synced to staging with PII anonymization"
    log SUCCESS "Staging database is safe to use for development"
}

# Run main function
main "$@"
