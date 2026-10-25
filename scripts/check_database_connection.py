#!/usr/bin/env python3
"""Read-only connection check for the Docker Windows recovery launcher.

Exit 0: password verified; 10: authentication mismatch; 20: other failure;
30: a wrong-password witness also connected, so automatic recovery is refused.
Never print a connection exception, DSN, password, or database record.
"""
import os
import secrets
from urllib.parse import unquote, urlsplit

import psycopg


def authentication_failure(error):
    # libpq may omit SQLSTATE for errors during initial connection.
    return (
        getattr(error, 'sqlstate', None) == '28P01'
        or 'password authentication failed' in str(error).lower()
    )


def query(connection_string, **overrides):
    with psycopg.connect(
        connection_string,
        connect_timeout=5,
        options='-c default_transaction_read_only=on',
        **overrides,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            if cursor.fetchone() != (1,):
                raise ValueError('Unexpected connection check result.')


def main():
    connection_string = os.environ.get('DATABASE_URL', '')
    try:
        parsed = urlsplit(connection_string)
        if (
            parsed.scheme not in ('postgres', 'postgresql')
            or parsed.hostname != 'db'
            or parsed.port not in (None, 5432)
            or not parsed.username
            or not parsed.path.strip('/')
            or parsed.query
            or unquote(parsed.username) != os.environ.get('POSTGRES_USER', '')
            or unquote(parsed.path.lstrip('/')) != os.environ.get('POSTGRES_DB', '')
            or not parsed.password
            or unquote(parsed.password) != os.environ.get('POSTGRES_PASSWORD', '')
        ):
            raise ValueError('Unsupported database target.')
    except ValueError:
        print('Diagnostic interrompu : configuration Docker TVM non reconnue.')
        return 20
    try:
        query(connection_string)
    except (psycopg.Error, ValueError) as error:
        if authentication_failure(error):
            print('Diagnostic : mot de passe de connexion refuse par PostgreSQL.')
            return 10
        print('Diagnostic : base inaccessible ou configuration non prise en charge.')
        return 20

    try:
        query(connection_string, password=secrets.token_urlsafe(48))
    except psycopg.Error as error:
        if not authentication_failure(error):
            print('Diagnostic incomplet : controle du mot de passe indisponible.')
            return 20
    except ValueError:
        print('Diagnostic incomplet : resultat de connexion inattendu.')
        return 20
    else:
        print('Diagnostic interrompu : la base accepte aussi un mot de passe incorrect.')
        return 30
    print('Connexion TVM a PostgreSQL verifiee ; aucune donnee modifiee.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
