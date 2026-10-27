#!/usr/bin/env bash
# Real Chromium + dedicated PostgreSQL database, never the business database.
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
set -a
source .env
set +a
export npm_config_cache="$task_root/.local/npm-cache"
export TVM_DEMO_MODE=1
# Browser acceptance must never invoke a paid provider or send notifications,
# even if the operator has configured credentials in their private .env.
export TVM_AI_ENABLED=0
export TVM_AI_API_KEY=
export TVM_EMAIL_ENABLED=0
export TVM_WHATSAPP_ENABLED=0
export TVM_MEDIA_ROOT="$task_root/.local/e2e-media"
TVM_DEMO_PASSWORD="$("$task_root/.venv/bin/python" - <<'PY'
import os, secrets
from pathlib import Path
folder=Path('.local')
folder.mkdir(mode=0o700,exist_ok=True)
target=folder/'e2e-password'
if target.exists():
    password=target.read_text().strip()
else:
    password=os.environ.get('TVM_DEMO_PASSWORD') or secrets.token_urlsafe(24)
    fd=os.open(target,os.O_WRONLY | os.O_CREAT | os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as output:
        output.write(password+'\n')
if len(password)<10:
    raise SystemExit('Mot de passe E2E local invalide.')
print(password)
PY
)"
export TVM_DEMO_PASSWORD
docker compose up -d --wait db
task_e2e_exists="$(docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '\''tvm_e2e'\''"')"
if [[ "$task_e2e_exists" != "1" ]]; then
  docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" tvm_e2e'
fi
DATABASE_URL="$("$task_root/.venv/bin/python" -c 'import os,urllib.parse; p=urllib.parse.urlsplit(os.environ["DATABASE_URL"]); print(urllib.parse.urlunsplit(p._replace(path="/tvm_e2e")))')"
export DATABASE_URL
cd backend
"$task_root/.venv/bin/python" manage.py migrate --noinput
"$task_root/.venv/bin/python" manage.py seed_demo
cd "$task_root/tests/browser"
if [[ ! -f package-lock.json ]]; then npm install; else npm ci; fi
if command -v chromium > /dev/null; then
  export TVM_CHROMIUM_PATH="$(command -v chromium)"
elif [[ -z "${TVM_CHROMIUM_PATH:-}" ]]; then
  npx playwright install chromium
fi
cd "$task_root/backend"
"$task_root/.venv/bin/gunicorn" config.wsgi:application --no-control-socket --bind 127.0.0.1:8001 --workers 2 --access-logfile "$task_root/.local/e2e-server.log" --error-logfile "$task_root/.local/e2e-server.log" &
task_server_pid=$!
trap 'kill "$task_server_pid" 2>/dev/null || true' EXIT
"$task_root/.venv/bin/python" - <<'PY'
import time, urllib.request
for attempt in range(50):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8001/api/session/', timeout=2) as r:
            if r.status == 200: break
    except OSError:
        time.sleep(0.2)
else:
    raise SystemExit('Le serveur E2E ne répond pas. Voir .local/e2e-server.log.')
PY
cd "$task_root/tests/browser"
npm test -- "$@"
