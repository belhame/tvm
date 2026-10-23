#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
umask 077
mkdir -p .local/backups
backup_path=".local/backups/tvm-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_path"
if [[ ! -s "$backup_path" ]]; then echo 'Sauvegarde vide.' >&2; exit 1; fi
docker compose exec -T db pg_restore --list < "$backup_path" > /dev/null
echo "Sauvegarde vérifiée : $backup_path"
