#!/bin/bash
set -euo pipefail

# Script: Migrate Data from Old Schema to New Schema
# Purpose: Copy and transform data in batches with throttling
# Usage: ./scripts/2_migrate_data.sh [--dry-run] [--batch-size N] [--throttle-ms N]

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Default settings
BATCH_SIZE="${BATCH_SIZE:-10000}"
THROTTLE_MS="${THROTTLE_MS:-100}"
DRY_RUN="${DRY_RUN:-false}"
MIGRATION_ID="users_name_split_$(date +%Y%m%d_%H%M%S)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_progress() {
    echo -e "${CYAN}[PROGRESS]${NC} $1"
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --batch-size)
                BATCH_SIZE="$2"
                shift 2
                ;;
            --throttle-ms)
                THROTTLE_MS="$2"
                shift 2
                ;;
            --help)
                echo "Usage: $0 [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --dry-run           Show what would be done without doing it"
                echo "  --batch-size N      Number of rows per batch (default: 10000)"
                echo "  --throttle-ms N     Milliseconds to wait between batches (default: 100)"
                echo "  --help              Show this help message"
                echo ""
                echo "Environment variables:"
                echo "  DATABASE_URL        PostgreSQL connection string"
                echo "  BATCH_SIZE          Default batch size"
                echo "  THROTTLE_MS         Default throttle delay"
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done
}

# Check environment
check_env() {
    log_info "Checking environment..."

    if [ -z "${DATABASE_URL:-}" ]; then
        log_error "DATABASE_URL not set"
        exit 1
    fi

    if ! command -v psql &> /dev/null; then
        log_error "psql not found in PATH"
        exit 1
    fi

    if ! psql "$DATABASE_URL" -c "SELECT 1" > /dev/null 2>&1; then
        log_error "Cannot connect to database"
        exit 1
    fi

    log_success "Environment OK"
}

# Get migration status
get_migration_status() {
    log_info "Checking migration status..."

    local status
    status=$(psql "$DATABASE_URL" -t -A << EOF
SELECT
    json_build_object(
        'total_rows', (SELECT COUNT(*) FROM public.users),
        'migrated_rows', (SELECT COUNT(*) FROM new_users.users),
        'last_checkpoint', (
            SELECT COALESCE(MAX(last_migrated_id), 0)
            FROM migration_checkpoint
            WHERE migration_id = '$MIGRATION_ID'
        )
    );
EOF
)

    echo "$status"
}

# Display migration plan
show_migration_plan() {
    log_info "Migration Plan:"
    echo ""
    echo "  Migration ID:    $MIGRATION_ID"
    echo "  Batch Size:      $BATCH_SIZE rows"
    echo "  Throttle:        $THROTTLE_MS ms between batches"
    echo "  Dry Run:         $DRY_RUN"
    echo ""

    local status
    status=$(get_migration_status)

    local total_rows migrated_rows last_checkpoint
    total_rows=$(echo "$status" | jq -r '.total_rows')
    migrated_rows=$(echo "$status" | jq -r '.migrated_rows')
    last_checkpoint=$(echo "$status" | jq -r '.last_checkpoint')

    echo "  Current Status:"
    echo "    Total rows (old schema):    $total_rows"
    echo "    Migrated rows (new schema): $migrated_rows"
    echo "    Last checkpoint ID:         $last_checkpoint"
    echo ""

    local remaining=$((total_rows - migrated_rows))
    local batches=$((remaining / BATCH_SIZE + 1))
    local estimated_seconds=$((batches * THROTTLE_MS / 1000))
    local estimated_minutes=$((estimated_seconds / 60))

    if [ "$remaining" -gt 0 ]; then
        echo "  Estimates:"
        echo "    Remaining rows:    $remaining"
        echo "    Batches needed:    $batches"
        echo "    Estimated time:    ${estimated_minutes} minutes"
        echo ""
    else
        log_success "Data migration already complete!"
        echo ""
        exit 0
    fi
}

# Initialize checkpoint
initialize_checkpoint() {
    if [ "$DRY_RUN" = true ]; then
        return
    fi

    log_info "Initializing migration checkpoint..."

    psql "$DATABASE_URL" > /dev/null << EOF
INSERT INTO migration_checkpoint (migration_id, last_migrated_id, rows_migrated)
VALUES ('$MIGRATION_ID', 0, 0)
ON CONFLICT (migration_id) DO NOTHING;
EOF

    log_success "Checkpoint initialized"
}

# Update checkpoint
update_checkpoint() {
    local last_id=$1
    local rows_count=$2

    if [ "$DRY_RUN" = true ]; then
        return
    fi

    psql "$DATABASE_URL" > /dev/null << EOF
UPDATE migration_checkpoint
SET last_migrated_id = $last_id,
    rows_migrated = rows_migrated + $rows_count,
    updated_at = NOW()
WHERE migration_id = '$MIGRATION_ID';
EOF
}

# Migrate one batch
migrate_batch() {
    local start_id=$1
    local end_id=$2

    if [ "$DRY_RUN" = true ]; then
        log_info "DRY RUN: Would migrate rows with id BETWEEN $start_id AND $end_id"
        return 0
    fi

    # Execute migration
    psql "$DATABASE_URL" << EOF
-- Temporarily disable triggers to avoid double-syncing
ALTER TABLE new_users.users DISABLE TRIGGER trigger_sync_to_old_users;

-- Insert with transformation
INSERT INTO new_users.users (id, email, first_name, last_name, bio, created_at, updated_at)
SELECT
    id,
    email,
    (split_full_name(full_name)).first_name,
    (split_full_name(full_name)).last_name,
    bio,
    created_at,
    updated_at
FROM public.users
WHERE id BETWEEN $start_id AND $end_id
ON CONFLICT (id) DO UPDATE SET
    email = EXCLUDED.email,
    first_name = EXCLUDED.first_name,
    last_name = EXCLUDED.last_name,
    bio = EXCLUDED.bio,
    updated_at = EXCLUDED.updated_at;

-- Re-enable triggers
ALTER TABLE new_users.users ENABLE TRIGGER trigger_sync_to_old_users;
EOF

    return $?
}

# Draw progress bar
draw_progress_bar() {
    local current=$1
    local total=$2
    local width=50

    local percentage=$((current * 100 / total))
    local filled=$((width * current / total))
    local empty=$((width - filled))

    printf "\r["
    printf "%${filled}s" | tr ' ' '='
    printf ">"
    printf "%${empty}s" | tr ' ' ' '
    printf "] %3d%% (%'d / %'d)" "$percentage" "$current" "$total"
}

# Migrate all data
migrate_all_data() {
    log_info "Starting data migration..."
    echo ""

    # Get total rows and starting point
    local status
    status=$(get_migration_status)

    local total_rows migrated_rows last_checkpoint
    total_rows=$(echo "$status" | jq -r '.total_rows')
    migrated_rows=$(echo "$status" | jq -r '.migrated_rows')
    last_checkpoint=$(echo "$status" | jq -r '.last_checkpoint')

    if [ "$total_rows" -eq 0 ]; then
        log_warning "No data to migrate (old schema is empty)"
        return
    fi

    # Get min and max IDs
    local min_id max_id
    read -r min_id max_id <<< "$(psql "$DATABASE_URL" -t -A << EOF
SELECT
    COALESCE(MIN(id), 0),
    COALESCE(MAX(id), 0)
FROM public.users
WHERE id > $last_checkpoint;
EOF
)"

    if [ "$min_id" -eq 0 ] || [ "$max_id" -eq 0 ]; then
        log_success "All data already migrated!"
        return
    fi

    # Initialize checkpoint
    initialize_checkpoint

    # Migrate in batches
    local current_id=$min_id
    local batch_num=0
    local total_batches=$(( (max_id - min_id) / BATCH_SIZE + 1 ))
    local start_time=$(date +%s)

    while [ "$current_id" -le "$max_id" ]; do
        local end_id=$((current_id + BATCH_SIZE - 1))
        if [ "$end_id" -gt "$max_id" ]; then
            end_id=$max_id
        fi

        batch_num=$((batch_num + 1))

        # Show progress
        draw_progress_bar "$batch_num" "$total_batches"

        # Migrate batch
        if ! migrate_batch "$current_id" "$end_id"; then
            echo ""
            log_error "Failed to migrate batch: $current_id to $end_id"
            exit 1
        fi

        # Update checkpoint
        update_checkpoint "$end_id" "$BATCH_SIZE"

        # Throttle
        if [ "$THROTTLE_MS" -gt 0 ] && [ "$current_id" -lt "$max_id" ]; then
            sleep "$(echo "scale=3; $THROTTLE_MS / 1000" | bc)"
        fi

        current_id=$((end_id + 1))
    done

    echo ""  # New line after progress bar

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local rows_per_second=$((total_rows / duration))

    log_success "Data migration complete!"
    echo ""
    echo "  Statistics:"
    echo "    Total rows:        $total_rows"
    echo "    Total batches:     $total_batches"
    echo "    Duration:          ${duration}s"
    echo "    Throughput:        $rows_per_second rows/sec"
    echo ""
}

# Verify migration
verify_migration() {
    log_info "Verifying migration..."

    local verification
    verification=$(psql "$DATABASE_URL" -t << 'EOF'
WITH counts AS (
    SELECT
        (SELECT COUNT(*) FROM public.users) as old_count,
        (SELECT COUNT(*) FROM new_users.users) as new_count
),
sample AS (
    SELECT
        o.id,
        o.full_name,
        n.first_name,
        n.last_name,
        concat_names(n.first_name, n.last_name) as reconstructed
    FROM public.users o
    JOIN new_users.users n ON o.id = n.id
    ORDER BY RANDOM()
    LIMIT 1000
)
SELECT json_build_object(
    'count_match', (SELECT old_count = new_count FROM counts),
    'old_count', (SELECT old_count FROM counts),
    'new_count', (SELECT new_count FROM counts),
    'sample_size', (SELECT COUNT(*) FROM sample),
    'sample_matches', (
        SELECT COUNT(*)
        FROM sample
        WHERE TRIM(full_name) = TRIM(reconstructed)
    ),
    'accuracy', (
        SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE TRIM(full_name) = TRIM(reconstructed)) / COUNT(*), 2)
        FROM sample
    )
);
EOF
)

    local count_match old_count new_count accuracy
    count_match=$(echo "$verification" | jq -r '.count_match')
    old_count=$(echo "$verification" | jq -r '.old_count')
    new_count=$(echo "$verification" | jq -r '.new_count')
    accuracy=$(echo "$verification" | jq -r '.accuracy')

    echo ""
    echo "  Verification Results:"
    echo "    Old schema rows:   $old_count"
    echo "    New schema rows:   $new_count"
    echo "    Count match:       $count_match"
    echo "    Sample accuracy:   ${accuracy}%"
    echo ""

    if [ "$count_match" = "true" ] && (( $(echo "$accuracy >= 99.9" | bc -l) )); then
        log_success "Migration verification passed!"
        return 0
    else
        log_error "Migration verification failed!"
        return 1
    fi
}

# Main execution
main() {
    parse_args "$@"

    echo ""
    echo "======================================"
    echo "  Data Migration: Old → New Schema"
    echo "======================================"
    echo ""

    check_env
    show_migration_plan

    if [ "$DRY_RUN" = true ]; then
        log_info "DRY RUN MODE - No changes will be made"
        echo ""
        exit 0
    fi

    # Confirm before proceeding
    read -p "Proceed with migration? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        log_info "Migration cancelled"
        exit 0
    fi

    echo ""
    migrate_all_data
    verify_migration

    echo ""
    log_success "Data migration complete!"
    echo ""
    echo "Next steps:"
    echo "  1. Monitor application for errors"
    echo "  2. Run verification: ./scripts/3_verify.sh"
    echo "  3. When ready, cutover: ./scripts/4_cutover.sh"
    echo ""
}

# Run main
main "$@"
