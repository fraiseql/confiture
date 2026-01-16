#!/bin/bash

################################################################################
# Confiture Database Setup Script
# Initializes PostgreSQL databases for local development and testing
#
# Usage:
#   ./scripts/setup-databases.sh                    # Setup with defaults
#   ./scripts/setup-databases.sh --user postgres   # Setup with specific user
#   ./scripts/setup-databases.sh --host remote-db  # Setup remote database
#   ./scripts/setup-databases.sh --clean            # Clean and recreate
#
# Requirements:
#   - PostgreSQL installed and running
#   - psql available in PATH
#   - User has createdb privileges
################################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration defaults
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${DB_PASSWORD:-}"
CLEAN_FIRST=false
VERBOSE=false

# Database names
PRIMARY_DB="confiture_test"
SOURCE_DB="confiture_source_test"
TARGET_DB="confiture_target_test"
DATABASES=($PRIMARY_DB $SOURCE_DB $TARGET_DB)

################################################################################
# Functions
################################################################################

print_header() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

log() {
    if [ "$VERBOSE" = true ]; then
        echo "  $1"
    fi
}

# Test PostgreSQL connection
test_connection() {
    local test_cmd="psql -h $DB_HOST -p $DB_PORT -U $DB_USER -tc \"SELECT 1\""

    if [ -n "$DB_PASSWORD" ]; then
        PGPASSWORD="$DB_PASSWORD" eval $test_cmd > /dev/null 2>&1
    else
        eval $test_cmd > /dev/null 2>&1
    fi

    if [ $? -eq 0 ]; then
        return 0
    else
        return 1
    fi
}

# Execute PostgreSQL command
exec_sql() {
    local sql_cmd="$1"
    local psql_cmd="psql -h $DB_HOST -p $DB_PORT -U $DB_USER -tc \"$sql_cmd\""

    if [ -n "$DB_PASSWORD" ]; then
        PGPASSWORD="$DB_PASSWORD" eval $psql_cmd
    else
        eval $psql_cmd
    fi
}

# Create database
create_database() {
    local db_name=$1

    log "Creating database: $db_name"

    if exec_sql "CREATE DATABASE \"$db_name\"" 2>/dev/null; then
        print_success "Database created: $db_name"
        return 0
    else
        # Check if already exists
        if exec_sql "SELECT 1 FROM pg_database WHERE datname = '$db_name'" | grep -q 1; then
            print_warning "Database already exists: $db_name"
            return 0
        else
            print_error "Failed to create database: $db_name"
            return 1
        fi
    fi
}

# Drop database
drop_database() {
    local db_name=$1

    log "Dropping database: $db_name"

    if exec_sql "DROP DATABASE IF EXISTS \"$db_name\"" 2>/dev/null; then
        print_success "Database dropped: $db_name"
        return 0
    else
        print_error "Failed to drop database: $db_name"
        return 1
    fi
}

# Create extensions
create_extensions() {
    local db_name=$1
    local extensions=("uuid-ossp" "pg_trgm")

    for ext in "${extensions[@]}"; do
        log "Creating extension: $ext in $db_name"
        exec_sql "CREATE EXTENSION IF NOT EXISTS \"$ext\"" > /dev/null 2>&1
    done

    print_success "Extensions created in: $db_name"
}

# Show usage
show_usage() {
    cat << EOF
${BLUE}Confiture Database Setup Script${NC}

Usage: $0 [OPTIONS]

Options:
  -h, --host HOST           PostgreSQL host (default: localhost)
  -p, --port PORT           PostgreSQL port (default: 5432)
  -u, --user USER           PostgreSQL user (default: postgres)
  -w, --password PASSWORD   PostgreSQL password
  -c, --clean               Drop databases before creating
  -v, --verbose             Verbose output
  --help                    Show this help message

Environment Variables:
  DB_HOST                   PostgreSQL host
  DB_PORT                   PostgreSQL port
  DB_USER                   PostgreSQL user
  DB_PASSWORD               PostgreSQL password

Examples:
  # Setup with defaults (localhost, postgres)
  $0

  # Setup with custom user and password
  $0 --user confiture --password secret

  # Clean and recreate all databases
  $0 --clean

  # Setup remote database with verbose output
  $0 --host production.db.com --verbose

EOF
}

################################################################################
# Main
################################################################################

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--host)
            DB_HOST="$2"
            shift 2
            ;;
        -p|--port)
            DB_PORT="$2"
            shift 2
            ;;
        -u|--user)
            DB_USER="$2"
            shift 2
            ;;
        -w|--password)
            DB_PASSWORD="$2"
            shift 2
            ;;
        -c|--clean)
            CLEAN_FIRST=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        --help)
            show_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

print_header "Confiture Database Setup"

# Print configuration
print_info "Configuration:"
echo "  Host:     $DB_HOST"
echo "  Port:     $DB_PORT"
echo "  User:     $DB_USER"
echo "  Password: $([ -n "$DB_PASSWORD" ] && echo "***" || echo "none")"
echo ""

# Test connection
print_info "Testing PostgreSQL connection..."
if test_connection; then
    print_success "PostgreSQL connection successful"
else
    print_error "Failed to connect to PostgreSQL"
    echo ""
    echo "Please ensure:"
    echo "  1. PostgreSQL is running on $DB_HOST:$DB_PORT"
    echo "  2. User '$DB_USER' exists and has createdb privileges"
    echo "  3. Password is correct (if required)"
    exit 1
fi

# Clean if requested
if [ "$CLEAN_FIRST" = true ]; then
    print_header "Cleaning Existing Databases"
    for db in "${DATABASES[@]}"; do
        drop_database "$db"
    done
fi

# Create databases
print_header "Creating Databases"
for db in "${DATABASES[@]}"; do
    if create_database "$db"; then
        create_extensions "$db"
    else
        print_error "Failed to setup database: $db"
        exit 1
    fi
done

# Verify setup
print_header "Verifying Setup"
for db in "${DATABASES[@]}"; do
    result=$(exec_sql "SELECT datname FROM pg_database WHERE datname = '$db'" 2>/dev/null)
    if [ -n "$result" ]; then
        print_success "Database verified: $db"
    else
        print_error "Database not found: $db"
        exit 1
    fi
done

# Summary
print_header "Setup Complete"
echo "Databases created and ready for use:"
for db in "${DATABASES[@]}"; do
    echo "  • $db"
done

echo ""
print_info "Connection strings:"
for db in "${DATABASES[@]}"; do
    if [ -n "$DB_PASSWORD" ]; then
        echo "  postgresql://$DB_USER:***@$DB_HOST:$DB_PORT/$db"
    else
        echo "  postgresql://$DB_HOST:$DB_PORT/$db"
    fi
done

echo ""
print_info "To test the setup, run:"
echo "  uv run pytest tests/ -v"

echo ""
echo -e "${GREEN}✓ Database infrastructure setup complete!${NC}\n"
