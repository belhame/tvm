#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
if [[ ! -f .env || ! -x .venv/bin/gunicorn ]]; then
  echo 'Exécutez d’abord bash scripts/setup.sh (ou --demo).' >&2
  exit 1
fi
set -a
source .env
set +a
docker compose up -d --wait db
cd backend
"$task_root/.venv/bin/python" manage.py migrate --noinput
exec "$task_root/.venv/bin/gunicorn" config.wsgi:application --no-control-socket --bind "${TVM_BIND:-127.0.0.1:8000}" --workers "${TVM_WORKERS:-3}" --timeout 60 --access-logfile - --error-logfile -
