#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)
BACKUP_DIR="${BACKUP_DIR:-/root/backups}"
LOG_FILE="${LOG_FILE:-$BACKUP_DIR/grader_db_backup.log}"

timestamp="$(date +%Y%m%d)"
tmp_file="$BACKUP_DIR/grader_${timestamp}.sql.gz.tmp"
final_file="$BACKUP_DIR/grader_${timestamp}.sql.gz"

mkdir -p "$BACKUP_DIR"
cd "$REPO_DIR"

cleanup_failed_backup() {
    rm -f "$tmp_file"
}

trap cleanup_failed_backup ERR

run_backup() {
    echo "[$(date -Is)] Starting PostgreSQL backup"

    docker compose "${COMPOSE_FILES[@]}" exec -T postgres sh -lc \
        'set -eu
        export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
        pg_dump -U "${POSTGRES_USER:?POSTGRES_USER is required}" "${POSTGRES_DB:?POSTGRES_DB is required}"' \
        | gzip > "$tmp_file"

    if [ ! -s "$tmp_file" ]; then
        echo "[$(date -Is)] Backup failed: archive is empty"
        return 1
    fi

    mv "$tmp_file" "$final_file"
    echo "[$(date -Is)] Backup completed: $final_file"
}

run_backup >> "$LOG_FILE" 2>&1
trap - ERR
