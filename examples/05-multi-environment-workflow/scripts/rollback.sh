#!/bin/bash
# Emergency rollback script
# Usage: ./scripts/rollback.sh <environment>

set -e  # Exit on error

ENV=$1

if [ -z "$ENV" ]; then
  echo "Usage: ./scripts/rollback.sh <environment>"
  echo "Example: ./scripts/rollback.sh production"
  exit 1
fi

echo "⚠️  EMERGENCY ROLLBACK for $ENV"
echo "──────────────────────────────────────────────"
echo "This will rollback the last migration"
echo ""

# Confirmation prompt
read -p "Are you sure? (type 'rollback'): " confirm

if [ "$confirm" != "rollback" ]; then
  echo "Aborted"
  exit 1
fi

echo ""
echo "📊 Current migration status:"
confiture migrate status --config "db/environments/$ENV.yaml"

echo ""
read -p "Continue with rollback? (y/N): " continue

if [ "$continue" != "y" ] && [ "$continue" != "Y" ]; then
  echo "Aborted"
  exit 1
fi

# Create emergency backup
echo ""
echo "💾 Creating emergency backup..."
BACKUP_FILE="emergency-backup-$(date +%Y%m%d-%H%M%S).sql"

case "$ENV" in
  production)
    DB_HOST="${PRODUCTION_DB_HOST}"
    DB_USER="${PRODUCTION_DB_USER}"
    DB_NAME="${PRODUCTION_DB_NAME}"
    ;;
  staging)
    DB_HOST="${STAGING_DB_HOST}"
    DB_USER="${STAGING_DB_USER}"
    DB_NAME="${STAGING_DB_NAME}"
    ;;
  *)
    DB_HOST="localhost"
    DB_USER="postgres"
    DB_NAME="confiture_${ENV}"
    ;;
esac

pg_dump -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" > "$BACKUP_FILE"
echo "✅ Backup created: $BACKUP_FILE"

# Perform rollback
echo ""
echo "🔄 Rolling back last migration..."
confiture migrate down --config "db/environments/$ENV.yaml" --verbose

# Verify rollback
echo ""
echo "🔍 Verifying rollback..."
./scripts/verify_migration.sh "$ENV"

# Check migration status
echo ""
echo "📊 New migration status:"
confiture migrate status --config "db/environments/$ENV.yaml"

echo ""
echo "──────────────────────────────────────────────"
echo "✅ Rollback complete for $ENV"
echo ""
echo "Next steps:"
echo "  1. Verify application is functioning correctly"
echo "  2. Monitor for errors"
echo "  3. Investigate why migration failed"
echo "  4. Fix migration code"
echo "  5. Test in staging before re-deploying"
echo ""
echo "Emergency backup saved: $BACKUP_FILE"
echo ""
