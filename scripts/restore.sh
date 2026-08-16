#!/bin/sh
# Restore a dump produced by scripts/backup.sh. Brief 11.
#
#   RESTORE_CONFIRM=si ./scripts/restore.sh backups/vectron-db-20260816-030000.dump
#
# DESTRUCTIVE: every table in the target database is dropped and rebuilt from
# the dump. The target is DATABASE_URL — point it at the database you actually
# mean to overwrite, and read it twice.
#
# RESTORE_CONFIRM=si is required because the difference between "restore the
# staging copy" and "wipe production" is one environment variable, and a script
# that runs on a bare invocation will eventually run on the wrong one.
set -e

DUMP_FILE="$1"

if [ -z "$DUMP_FILE" ]; then
    echo "Uso: RESTORE_CONFIRM=si $0 <archivo.dump>" >&2
    exit 1
fi

if [ ! -f "$DUMP_FILE" ]; then
    echo "ERROR: no existe el archivo $DUMP_FILE" >&2
    exit 1
fi

if [ -z "$DATABASE_URL" ]; then
    echo "ERROR: falta DATABASE_URL." >&2
    exit 1
fi

if [ "$RESTORE_CONFIRM" != "si" ]; then
    echo "ERROR: esto BORRA y reescribe la base de datos apuntada por DATABASE_URL." >&2
    echo "Si es lo que quiere, vuelva a correrlo con RESTORE_CONFIRM=si" >&2
    exit 1
fi

# --clean --if-exists drops each object before recreating it, so restoring over
# a database that already has tables works instead of failing halfway.
# --no-owner reassigns everything to the connecting role: managed providers do
# not let you create the role the dump was taken from.
# --exit-on-error is what turns a partial restore into a failure. Without it
# pg_restore reports errors and still exits 0, and "restored with 200 errors"
# reads exactly like success in a log.
echo "Restaurando $DUMP_FILE ..."
pg_restore \
    --clean \
    --if-exists \
    --no-owner \
    --exit-on-error \
    --dbname="$DATABASE_URL" \
    "$DUMP_FILE"

echo "Restauración terminada. Verifique con:"
echo "  python manage.py check && python manage.py showmigrations | tail -5"
