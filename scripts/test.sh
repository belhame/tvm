#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
set -a
source .env
set +a
docker compose up -d --wait db
cd backend
"$task_root/.venv/bin/python" manage.py test core --noinput
cd "$task_root/frontend"
npm run build
