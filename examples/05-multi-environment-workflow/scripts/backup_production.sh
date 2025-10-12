#!/bin/bash
# Backup production database before migration
# Usage: ./scripts/backup_production.sh

set -e  # Exit on error

echo "💾 Backing up production database..."
echo "──────────────────────────────────────────────"

# Configuration from environment variables
DB_HOST="${PRODUCTION_DB_HOST}"
DB_PORT="${PRODUCTION_DB_PORT:-5432}"
DB_NAME="${PRODUCTION_DB_NAME}"
DB_USER="${PRODUCTION_DB_USER}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/production-backup-${TIMESTAMP}.sql"

# Validate required variables
if [ -z "$DB_HOST" ] || [ -z "$DB_NAME" ] || [ -z "$DB_USER" ]; then
  echo "❌ Error: Missing required environment variables"
  echo "Required: PRODUCTION_DB_HOST, PRODUCTION_DB_NAME, PRODUCTION_DB_USER"
  exit 1
fi

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Perform backup
echo "📦 Creating backup..."
echo "  Host: $DB_HOST"
echo "  Database: $DB_NAME"
echo "  File: $BACKUP_FILE"
echo ""

pg_dump \
  -h "$DB_HOST" \
  -p "$DB_PORT" \
  -U "$DB_USER" \
  -d "$DB_NAME" \
  --format=plain \
  --no-owner \
  --no-privileges \
  --verbose \
  > "$BACKUP_FILE" 2>&1

# Get backup size
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)

echo ""
echo "✅ Backup created successfully"
echo "  File: $BACKUP_FILE"
echo "  Size: $BACKUP_SIZE"

# Compress backup
echo ""
echo "🗜️  Compressing backup..."
gzip "$BACKUP_FILE"
COMPRESSED_FILE="${BACKUP_FILE}.gz"
COMPRESSED_SIZE=$(du -h "$COMPRESSED_FILE" | cut -f1)

echo "✅ Backup compressed"
echo "  File: $COMPRESSED_FILE"
echo "  Size: $COMPRESSED_SIZE"

# Upload to S3 (if configured)
if [ -n "$AWS_S3_BUCKET" ]; then
  echo ""
  echo "☁️  Uploading to S3..."

  aws s3 cp "$COMPRESSED_FILE" \
    "s3://${AWS_S3_BUCKET}/backups/production/production-backup-${TIMESTAMP}.sql.gz" \
    --storage-class STANDARD_IA

  echo "✅ Uploaded to S3"
  echo "  Bucket: $AWS_S3_BUCKET"
  echo "  Key: backups/production/production-backup-${TIMESTAMP}.sql.gz"
  echo "  Retention: 30 days (lifecycle policy)"
else
  echo ""
  echo "⚠️  Warning: AWS_S3_BUCKET not set, skipping S3 upload"
  echo "  Backup is only stored locally: $COMPRESSED_FILE"
fi

# Cleanup old local backups (keep last 7 days)
echo ""
echo "🧹 Cleaning up old local backups..."
find "$BACKUP_DIR" -name "production-backup-*.sql.gz" -mtime +7 -delete
echo "✅ Removed backups older than 7 days"

echo ""
echo "──────────────────────────────────────────────"
echo "✅ Backup complete"
echo ""
echo "Recovery instructions:"
echo "  1. Download from S3 (if uploaded):"
echo "     aws s3 cp s3://${AWS_S3_BUCKET}/backups/production/production-backup-${TIMESTAMP}.sql.gz ."
echo ""
echo "  2. Decompress:"
echo "     gunzip production-backup-${TIMESTAMP}.sql.gz"
echo ""
echo "  3. Restore:"
echo "     psql -h \$DB_HOST -U \$DB_USER -d \$DB_NAME < production-backup-${TIMESTAMP}.sql"
echo ""
