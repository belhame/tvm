#!/usr/bin/env python3
"""Create local secrets once. Never print credentials or overwrite configuration."""
import argparse
import os
from pathlib import Path
import secrets

parser = argparse.ArgumentParser()
parser.add_argument('--demo', action='store_true')
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
target = root / '.env'
if target.exists():
    print('.env déjà présent, conservé sans modification.')
    raise SystemExit(0)
password = secrets.token_urlsafe(32)
demo_password = secrets.token_urlsafe(18) if args.demo else ''
values = {
    'POSTGRES_USER': 'tvm', 'POSTGRES_DB': 'tvm', 'POSTGRES_PASSWORD': password,
    'TVM_DB_PORT': '55432',
    'DATABASE_URL': f'postgresql://tvm:{password}@127.0.0.1:55432/tvm',
    'DJANGO_SECRET_KEY': secrets.token_urlsafe(64), 'DJANGO_DEBUG': '0',
    'DJANGO_ALLOWED_HOSTS': 'localhost,127.0.0.1',
    'DJANGO_CSRF_TRUSTED_ORIGINS': 'http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173,http://127.0.0.1:5173',
    'DJANGO_SECURE_COOKIES': '0', 'TVM_TIMEZONE': 'Africa/Lagos',
    'TVM_DEMO_MODE': '1' if args.demo else '0', 'TVM_DEMO_PASSWORD': demo_password,
}
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write('# Configuration locale générée ; ne pas versionner.\n')
    for name, value in values.items():
        f.write(f'{name}={value}\n')
if args.demo:
    local = root / '.local'
    local.mkdir(mode=0o700, exist_ok=True)
    access = local / 'demo-access.txt'
    fd = os.open(access, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write('PowerCare — comptes de démonstration fictifs\n')
        f.write('Comptes (installation neuve) : admin / responsable / technicien / livreur / client\n')
        f.write(f'Mot de passe local commun : {demo_password}\n')
        f.write('Ne pas ouvrir ces comptes à des utilisateurs réels.\n')
print('Configuration créée dans .env (permissions 600).')
if args.demo:
    print('Accès de démonstration enregistrés dans .local/demo-access.txt (permissions 600).')
