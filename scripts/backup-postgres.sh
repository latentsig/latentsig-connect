#!/bin/sh
set -eu

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
temporary="/backups/latentsig-${stamp}.dump.partial"
backup="/backups/latentsig-${stamp}.dump"

pg_dump --host "$PGHOST" --username "$PGUSER" --dbname "$PGDATABASE" --format=custom --no-owner --file "$temporary"
pg_restore --list "$temporary" >/dev/null
mv "$temporary" "$backup"
find /backups -type f -name 'latentsig-*.dump' -mtime +14 -delete
printf 'Verified PostgreSQL backup: %s\n' "$backup"
