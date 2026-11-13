#!/usr/bin/env bash
# Nightly backup of Versnq Core: the database (pg_dump) and uploaded files, kept 14 days in
# /opt/core-backups. Installed as /etc/cron.d/core-backup (docs/DEPLOYMENT.md). AMS untouched.
set -euo pipefail
cd /opt/core
OUT=/opt/core-backups
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP=$(date +%Y%m%d-%H%M)
mkdir -p "$OUT" && chmod 700 "$OUT"
C=(docker compose -f docker-compose.prod.yml --env-file .env.prod)

"${C[@]}" exec -T postgres pg_dump -U postgres --format=custom versnq > "$OUT/db-$STAMP.dump.part"
mv "$OUT/db-$STAMP.dump.part" "$OUT/db-$STAMP.dump"
"${C[@]}" exec -T backend tar -C /app/var -czf - files > "$OUT/files-$STAMP.tgz.part"
mv "$OUT/files-$STAMP.tgz.part" "$OUT/files-$STAMP.tgz"

find "$OUT" -name 'db-*.dump' -mtime +"$KEEP_DAYS" -delete
find "$OUT" -name 'files-*.tgz' -mtime +"$KEEP_DAYS" -delete
find "$OUT" -name '*.part' -delete
echo "$(date -Is) backup ok: db-$STAMP.dump files-$STAMP.tgz"
