#!/usr/bin/env bash
# A matching PostgreSQL + private file backup. Run after stopping any host server.
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
umask 077
mkdir -p .local/backups
task_stamp="$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"
task_base=".local/backups/tvm-$task_stamp"
task_running_services="$(docker compose --profile container ps --status running --services)"
task_writers=()
for task_service in web reminders; do
  if [[ $'\n'"$task_running_services"$'\n' == *$'\n'"$task_service"$'\n'* ]]; then
    task_writers+=("$task_service")
  fi
done
task_restore_writers() {
  if (( ${#task_writers[@]} )); then
    # `start --wait` is unavailable in some Compose versions. Restart the
    # existing containers without recreating them or changing their images.
    docker compose --profile container start "${task_writers[@]}" > /dev/null || printf 'Relancez DEMARRER_TVM.cmd pour redemarrer les services arretes pendant la sauvegarde.\n' >&2
  fi
}
trap task_restore_writers EXIT
# Stop the reminder worker before the web application so neither can write
# between the database snapshot and the private-file snapshot.
if [[ " ${task_writers[*]} " == *" reminders "* ]]; then
  docker compose --profile container stop reminders > /dev/null
fi
if [[ " ${task_writers[*]} " == *" web "* ]]; then
  docker compose stop web > /dev/null
fi
task_files=("$task_base.dump")
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$task_base.dump"
if [[ ! -s "$task_base.dump" ]]; then printf 'Sauvegarde PostgreSQL vide.\n' >&2; exit 1; fi
docker compose exec -T db pg_restore --list < "$task_base.dump" > /dev/null
# The installed DB image is reused; this helper never changes the private volume.
if docker volume inspect tvm-powercare_tvm_media > /dev/null 2>&1; then
  docker run --rm --mount type=volume,src=tvm-powercare_tvm_media,dst=/media,readonly postgres:16-alpine tar -C /media -czf - . > "$task_base-media.tar.gz"
  docker run --rm -i postgres:16-alpine tar -tzf - < "$task_base-media.tar.gz" > /dev/null
  task_files+=("$task_base-media.tar.gz")
fi
# Native Linux development uses this folder instead of the Docker file volume.
if [[ -d backend/media ]]; then
  tar -C backend/media -czf "$task_base-media-host.tar.gz" .
  tar -tzf "$task_base-media-host.tar.gz" > /dev/null
  task_files+=("$task_base-media-host.tar.gz")
fi
if [[ -f .env ]]; then
  cp .env "$task_base.env"
  task_files+=("$task_base.env")
fi
sha256sum "${task_files[@]}" > "$task_base.sha256"
sha256sum --check "$task_base.sha256" > /dev/null
printf 'Sauvegarde PostgreSQL et fichiers disponibles vérifiée : %s.*\n' "$task_base"
printf 'Conservez cet ensemble au même endroit ; le fichier .env de sauvegarde contient les accès privés.\n'
