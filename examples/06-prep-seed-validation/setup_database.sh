#!/bin/bash
# Setup script for prep-seed validation example
# Creates PostgreSQL database and schemas

set -e

# Configuration
DB_HOST="${DB_HOST:-localhost}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${DB_PASSWORD:-password}"
DB_NAME="${DB_NAME:-confiture_test}"

echo "🗄️  Setting up PostgreSQL database for prep-seed example"
echo "=================================================="
echo "Host: $DB_HOST"
echo "User: $DB_USER"
echo "Database: $DB_NAME"
echo ""

# Create database
echo "Creating database..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -c "CREATE DATABASE $DB_NAME;" 2>/dev/null || true

# Create schemas
echo "Creating schemas..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -c "CREATE SCHEMA IF NOT EXISTS prep_seed;"
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -c "CREATE SCHEMA IF NOT EXISTS catalog;"

# Create tables
echo "Creating tables..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -f db/schema/prep_seed/tb_manufacturer.sql
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -f db/schema/catalog/tb_manufacturer.sql

# Create functions
echo "Creating functions..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -f db/schema/functions/fn_resolve_tb_manufacturer.sql

# Load seed data
echo "Loading seed data..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -f db/seeds/prep/01_manufacturers.sql

echo ""
echo "✅ Database setup complete!"
echo ""
echo "To run validation:"
echo "  export DATABASE_URL='postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST/$DB_NAME'"
echo "  python validate_full.py"
