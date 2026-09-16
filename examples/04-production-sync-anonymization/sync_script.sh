#!/usr/bin/env bash
#
# Production → staging refresh with PII anonymization.
#
# An operator wrapper around `confiture sync`. Everything it adds is something
# confiture deliberately does not do: taking a backup before overwriting
# staging, running the SQL verification afterwards, and refusing to proceed when
# the preconditions are not met.
#
# Usage:
#   ./sync_script.sh [OPTIONS]
#
# Options:
#   --dry-run       Check every precondition and print the sync command, then stop
#   --skip-backup   Do not back staging up first (it is about to be overwritten)
#   --skip-verify   Do not run verify_anonymization.sql afterwards (NOT ADVISED)
#   --resume        Resume an interrupted sync from the checkpoint file
#   --json          Ask confiture for JSON output
#   -h, --help      This message
#
# Environment:
#   PROD_DB_PASSWORD       required — expanded into db/environments/production.yaml
#   STAGING_DB_PASSWORD    required — expanded into db/environments/staging.yaml
#   ANONYMIZATION_SECRET   required — the HMAC key behind every pseudonym
#
# Example:
#   export PROD_DB_PASSWORD=… STAGING_DB_PASSWORD=… ANONYMIZATION_SECRET=…
#   ./sync_script.sh --dry-run

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANON_CONFIG="${SCRIPT_DIR}/db/sync/anonymization.yaml"
VERIFY_SQL="${SCRIPT_DIR}/verify_anonymization.sql"
CHECKPOINT="${SCRIPT_DIR}/.sync-checkpoint.json"
LOG_FILE="${SCRIPT_DIR}/sync-$(date +%Y%m%d-%H%M%S).log"

# Tables that never leave production, masked or not. This is `--exclude` on the
# command line, not a key in the YAML: confiture's anonymization config says how
# to mask columns and nothing about which tables to copy.
EXCLUDE_TABLES="audit_logs"

DRY_RUN=false
SKIP_BACKUP=false
SKIP_VERIFY=false
RESUME=false
JSON=false

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; BLUE=$'\033[0;34m'; NC=$'\033[0m'

log() {
    local level=$1; shift
    local colour
    case $level in
        INFO)    colour=$BLUE   ;;
        SUCCESS) colour=$GREEN  ;;
        WARNING) colour=$YELLOW ;;
        ERROR)   colour=$RED    ;;
        *)       colour=$NC     ;;
    esac
    printf '%s[%s]%s %s\n' "$colour" "$level" "$NC" "$*" | tee -a "$LOG_FILE"
}

header() {
    printf '\n============================================================\n  %s\n============================================================\n\n' "$1"
}

# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

check_prerequisites() {
    log INFO "Checking prerequisites…"

    command -v confiture >/dev/null || { log ERROR "confiture not on PATH (pip install confiture)"; exit 1; }
    command -v psql      >/dev/null || { log ERROR "psql not on PATH"; exit 1; }

    [[ -f "$ANON_CONFIG" ]] || { log ERROR "anonymization config not found: $ANON_CONFIG"; exit 1; }

    if [[ "$SKIP_VERIFY" == "false" && ! -f "$VERIFY_SQL" ]]; then
        log ERROR "verification SQL not found: $VERIFY_SQL (or pass --skip-verify)"
        exit 1
    fi

    local missing=()
    [[ -n "${PROD_DB_PASSWORD:-}"     ]] || missing+=(PROD_DB_PASSWORD)
    [[ -n "${STAGING_DB_PASSWORD:-}"  ]] || missing+=(STAGING_DB_PASSWORD)
    # Without this, `confiture sync --anonymize` stops with CONFIG_009 rather
    # than falling back to a default key — there is no default key.
    [[ -n "${ANONYMIZATION_SECRET:-}" ]] || missing+=(ANONYMIZATION_SECRET)
    if (( ${#missing[@]} )); then
        log ERROR "unset environment variable(s): ${missing[*]}"
        exit 1
    fi

    log SUCCESS "Prerequisites OK"
}

check_config_parses() {
    # There is no `confiture validate-config` for this file — that command
    # validates a *migration* config, and `validate-profile` validates the
    # AnonymizationProfile shape, which is a different format. So check the two
    # things that are cheap to check here, and let `confiture sync` reject the
    # rest with CONFIG_002.
    log INFO "Checking $ANON_CONFIG parses…"
    python3 - "$ANON_CONFIG" <<'PY' || { log ERROR "anonymization config is not usable"; exit 1; }
import sys, yaml
STRATEGIES = {"email", "phone", "name", "hash", "redact"}
with open(sys.argv[1]) as fh:
    data = yaml.safe_load(fh)
if not isinstance(data, dict):
    sys.exit("top level must map table names to rule lists")
problems = []
for table, rules in data.items():
    if not isinstance(rules, list):
        problems.append(f"{table}: rules must be a list")
        continue
    for rule in rules:
        if not isinstance(rule, dict) or "column" not in rule or "strategy" not in rule:
            problems.append(f"{table}: every rule needs `column` and `strategy`")
        elif rule["strategy"] not in STRATEGIES:
            # confiture masks an unknown strategy to [REDACTED] rather than
            # failing, so a typo destroys a column quietly. Catch it here.
            problems.append(f"{table}.{rule['column']}: unknown strategy {rule['strategy']!r}")
if problems:
    sys.exit("\n".join(problems))
print(f"{len(data)} table(s) with rules")
PY
    log SUCCESS "Config OK"
}

# ---------------------------------------------------------------------------
# Backup — staging is about to be overwritten
# ---------------------------------------------------------------------------

backup_staging() {
    local backup_file="${SCRIPT_DIR}/staging-backup-$(date +%Y%m%d-%H%M%S).sql.gz"
    log INFO "Backing staging up to $(basename "$backup_file")…"

    # The environment files carry a single `database_url`, so pg_dump is given
    # that URL directly rather than reassembled from host/port/user parts.
    local staging_url
    staging_url="$(confiture_url staging)"

    if pg_dump "$staging_url" --no-owner --no-acl | gzip > "$backup_file"; then
        log SUCCESS "Backup written: $backup_file"
        log INFO    "Restore with: gunzip < $backup_file | psql \"\$STAGING_URL\""
    else
        log ERROR "Backup failed — refusing to overwrite staging"
        exit 1
    fi
}

# Resolve an environment's database_url, with ${VAR} expanded as confiture does.
confiture_url() {
    python3 - "$SCRIPT_DIR/db/environments/$1.yaml" <<'PY'
import os, re, sys, yaml
with open(sys.argv[1]) as fh:
    url = yaml.safe_load(fh)["database_url"]
print(re.sub(r"\$\{([A-Z_][A-Z0-9_]*)\}", lambda m: os.environ[m.group(1)], url))
PY
}

# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

build_sync_command() {
    # --from/--to take an environment name or a DSN. Environment names keep the
    # credentials out of argv and out of `ps aux`.
    local -a cmd=(confiture sync
        --from production
        --to staging
        --anonymize
        --anonymization-config "$ANON_CONFIG"
        --exclude "$EXCLUDE_TABLES"
        --checkpoint "$CHECKPOINT")
    [[ "$RESUME" == "true" ]] && cmd+=(--resume)
    [[ "$JSON"   == "true" ]] && cmd+=(--format json)
    printf '%s\n' "${cmd[@]}"
}

run_sync() {
    header "Production → Staging (anonymized)"
    log WARNING "This overwrites the staging database"

    local -a cmd
    mapfile -t cmd < <(build_sync_command)
    log INFO "Command: ${cmd[*]}"

    local start=$SECONDS
    if (cd "$SCRIPT_DIR" && "${cmd[@]}") 2>&1 | tee -a "$LOG_FILE"; then
        log SUCCESS "Sync finished in $((SECONDS - start))s"
    else
        log ERROR "Sync failed — see $LOG_FILE"
        log INFO  "Resume with: $0 --resume"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

verify() {
    header "Verification"
    log INFO "A green sync means rows moved, not that they were masked."

    local staging_url
    staging_url="$(confiture_url staging)"

    if psql "$staging_url" -v ON_ERROR_STOP=1 -f "$VERIFY_SQL" 2>&1 | tee -a "$LOG_FILE"; then
        log SUCCESS "No PII detected in staging"
    else
        log ERROR "VERIFICATION FAILED — treat staging as containing production PII"
        log ERROR "Restrict access and re-run the sync before anyone uses it"
        exit 1
    fi
}

# ---------------------------------------------------------------------------

main() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)     DRY_RUN=true      ;;
            --skip-backup) SKIP_BACKUP=true  ;;
            --skip-verify) SKIP_VERIFY=true  ;;
            --resume)      RESUME=true       ;;
            --json)        JSON=true         ;;
            -h|--help)     sed -n '2,29p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
            *)             echo "Unknown option: $1 (try --help)" >&2; exit 1 ;;
        esac
        shift
    done

    header "Confiture production sync with PII anonymization"
    log INFO "Log file: $LOG_FILE"

    check_prerequisites
    check_config_parses

    if [[ "$DRY_RUN" == "true" ]]; then
        header "Dry run — nothing will be copied"
        log INFO "Would run:"
        local -a would
        mapfile -t would < <(build_sync_command)
        printf '    %s\n' "${would[*]}"
        log INFO "Then: psql <staging> -v ON_ERROR_STOP=1 -f $(basename "$VERIFY_SQL")"
        exit 0
    fi

    [[ "$SKIP_BACKUP" == "true" ]] || backup_staging
    run_sync
    if [[ "$SKIP_VERIFY" == "true" ]]; then
        log WARNING "Verification skipped — PII may have reached staging unmasked"
    else
        verify
    fi

    header "Done"
    log SUCCESS "Staging refreshed with anonymized production data"
}

main "$@"
