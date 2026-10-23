#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
if [[ "${1:-}" != "" && "${1:-}" != "--demo" ]]; then
  echo 'Usage: bash scripts/setup.sh [--demo]' >&2
  exit 2
fi
python3 scripts/init_env.py "$@"
set -a
source .env
set +a
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
export PIP_CACHE_DIR="$task_root/.local/pip-cache"
export npm_config_cache="$task_root/.local/npm-cache"
.venv/bin/python -m pip install -r backend/requirements.lock.txt
docker compose up -d --wait db
cd frontend
npm ci
npm run build
cd "$task_root/backend"
"$task_root/.venv/bin/python" manage.py migrate --noinput
"$task_root/.venv/bin/python" manage.py collectstatic --noinput
"$task_root/.venv/bin/python" manage.py check
if [[ "${1:-}" == "--demo" ]]; then
  if [[ "${TVM_DEMO_MODE:-0}" != "1" ]]; then
    echo 'Le fichier .env existant désactive la démo. Conservé ; aucune donnée fictive ajoutée.' >&2
    exit 1
  fi
  "$task_root/.venv/bin/python" manage.py seed_demo
fi
echo 'Installation terminée. Démarrage : bash scripts/start.sh'
