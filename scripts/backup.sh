#!/bin/sh
# Daily backup: PostgreSQL dump (+ optional uploaded files). Brief 11.
#
#   ./scripts/backup.sh [destination-directory]
#
# Reads DATABASE_URL from the environment — the same variable the application
# uses, so a backup can never silently dump a different database than the one
# being served. Nothing is written to the repository and no credential is ever
# echoed: pg_dump receives the URL as an argument and prints only its own
# errors.
#
# Restoring is scripts/restore.sh. A backup nobody has restored is a guess, not
# a backup; CI restores one on every push (.github/workflows/ci.yml) so the two
# scripts cannot drift apart unnoticed.
set -e

if [ -z "$DATABASE_URL" ]; then
    echo "ERROR: falta DATABASE_URL." >&2
    exit 1
fi

BACKUP_DIR="${1:-${BACKUP_DIR:-./backups}}"
# How many days of dumps to keep. Disk is cheaper than a lost month.
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
STAMP=$(date +%Y%m%d-%H%M%S)
DUMP_FILE="$BACKUP_DIR/vectron-db-$STAMP.dump"

mkdir -p "$BACKUP_DIR"

# -Fc is PostgreSQL's compressed custom format: it is what pg_restore reads,
# it allows restoring a single table, and it is version-tolerant in a way a
# plain SQL file is not.
# --no-owner keeps the dump portable between a managed database (where the
# owner role is provider-specific) and a plain server.
echo "Respaldando la base de datos en $DUMP_FILE ..."
pg_dump --format=custom --no-owner --file="$DUMP_FILE" "$DATABASE_URL"

# Uploaded photos, manuals and documents live on disk, not in Postgres. A
# database-only backup restores work orders that point at files that no longer
# exist. Set MEDIA_ROOT_PATH to include them.
if [ -n "$MEDIA_ROOT_PATH" ] && [ -d "$MEDIA_ROOT_PATH" ]; then
    MEDIA_FILE="$BACKUP_DIR/vectron-media-$STAMP.tar.gz"
    echo "Respaldando los archivos subidos en $MEDIA_FILE ..."
    tar --create --gzip --file="$MEDIA_FILE" -C "$MEDIA_ROOT_PATH" .
fi

# Prune old copies. -mtime +N is "older than N days".
find "$BACKUP_DIR" -maxdepth 1 -name 'vectron-*' -type f -mtime "+$RETENTION_DAYS" -delete

echo "Listo. Contenido de $BACKUP_DIR:"
ls -lh "$BACKUP_DIR"
