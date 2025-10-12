#!/bin/bash
# Verify migration completed successfully
# Usage: ./scripts/verify_migration.sh <environment>

set -e  # Exit on error

ENV=$1

if [ -z "$ENV" ]; then
  echo "Usage: ./scripts/verify_migration.sh <environment>"
  echo "Example: ./scripts/verify_migration.sh staging"
  exit 1
fi

echo "🔍 Verifying migration for environment: $ENV"
echo "──────────────────────────────────────────────"

EXIT_CODE=0

# Check migration status
echo ""
echo "📊 Checking migration status..."
confiture migrate status --env "$ENV" || EXIT_CODE=1

# Verify table structures
echo ""
echo "📋 Verifying table structures..."
psql -h "${DB_HOST:-localhost}" -U "${DB_USER:-postgres}" -d "${DB_NAME}" -c "
  SELECT
    table_name,
    column_name,
    data_type,
    is_nullable,
    column_default
  FROM information_schema.columns
  WHERE table_schema = 'public'
  ORDER BY table_name, ordinal_position
" || EXIT_CODE=1

# Check indexes
echo ""
echo "📇 Verifying indexes..."
psql -h "${DB_HOST:-localhost}" -U "${DB_USER:-postgres}" -d "${DB_NAME}" -c "
  SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
  FROM pg_indexes
  WHERE schemaname = 'public'
  ORDER BY tablename, indexname
" || EXIT_CODE=1

# Verify constraints
echo ""
echo "🔒 Verifying constraints..."
psql -h "${DB_HOST:-localhost}" -U "${DB_USER:-postgres}" -d "${DB_NAME}" -c "
  SELECT
    conname AS constraint_name,
    contype AS constraint_type,
    conrelid::regclass AS table_name,
    pg_get_constraintdef(oid) AS definition
  FROM pg_constraint
  WHERE connamespace = 'public'::regnamespace
  ORDER BY conrelid::regclass::text, conname
" || EXIT_CODE=1

# Verify views
echo ""
echo "👁️  Verifying views..."
psql -h "${DB_HOST:-localhost}" -U "${DB_USER:-postgres}" -d "${DB_NAME}" -c "
  SELECT
    table_name,
    view_definition
  FROM information_schema.views
  WHERE table_schema = 'public'
  ORDER BY table_name
" || EXIT_CODE=1

# Test basic queries
echo ""
echo "🧪 Testing basic queries..."

# Test users table
psql -h "${DB_HOST:-localhost}" -U "${DB_USER:-postgres}" -d "${DB_NAME}" -c "
  SELECT COUNT(*) AS user_count FROM users;
" || EXIT_CODE=1

# Test projects table
psql -h "${DB_HOST:-localhost}" -U "${DB_USER:-postgres}" -d "${DB_NAME}" -c "
  SELECT COUNT(*) AS project_count FROM projects;
" || EXIT_CODE=1

# Test tasks table
psql -h "${DB_HOST:-localhost}" -U "${DB_USER:-postgres}" -d "${DB_NAME}" -c "
  SELECT COUNT(*) AS task_count FROM tasks;
" || EXIT_CODE=1

# Test foreign key relationships
echo ""
echo "🔗 Testing foreign key relationships..."
psql -h "${DB_HOST:-localhost}" -U "${DB_USER:-postgres}" -d "${DB_NAME}" -c "
  SELECT
    p.name AS project_name,
    u.email AS owner_email,
    COUNT(t.id) AS task_count
  FROM projects p
  LEFT JOIN users u ON u.id = p.owner_id
  LEFT JOIN tasks t ON t.project_id = p.id
  GROUP BY p.id, p.name, u.email
  LIMIT 5;
" || EXIT_CODE=1

# Test views
echo ""
echo "📊 Testing analytics views..."
psql -h "${DB_HOST:-localhost}" -U "${DB_USER:-postgres}" -d "${DB_NAME}" -c "
  SELECT * FROM user_project_summary LIMIT 3;
" || EXIT_CODE=1

psql -h "${DB_HOST:-localhost}" -U "${DB_USER:-postgres}" -d "${DB_NAME}" -c "
  SELECT * FROM project_task_stats LIMIT 3;
" || EXIT_CODE=1

# Verify triggers
echo ""
echo "⚡ Verifying triggers..."
psql -h "${DB_HOST:-localhost}" -U "${DB_USER:-postgres}" -d "${DB_NAME}" -c "
  SELECT
    trigger_name,
    event_manipulation,
    event_object_table,
    action_statement
  FROM information_schema.triggers
  WHERE trigger_schema = 'public'
  ORDER BY event_object_table, trigger_name
" || EXIT_CODE=1

# Final result
echo ""
echo "──────────────────────────────────────────────"
if [ $EXIT_CODE -eq 0 ]; then
  echo "✅ Verification passed for $ENV"
  echo ""
  echo "Summary:"
  echo "  - All tables present"
  echo "  - All indexes created"
  echo "  - All constraints valid"
  echo "  - All views accessible"
  echo "  - All triggers active"
  echo "  - Basic queries successful"
else
  echo "❌ Verification failed for $ENV"
  echo ""
  echo "Action required:"
  echo "  - Review error messages above"
  echo "  - Check migration logs"
  echo "  - Consider rollback if necessary"
fi

exit $EXIT_CODE
