#!/bin/sh
# Run only inside the existing PostgreSQL container, using its configured role.
# No volume deletion, HBA change, role creation, grant change or data restoration.
set -eu
umask 077

STATE_DIR=/tmp/tvm-connection-repair
LOCK_DIR=/tmp/tvm-connection-repair.lock
SOCKET_DIR=/var/run/postgresql
PHASE=${1:-}

fail() {
    printf '%s\n' "$1" >&2
    exit "${2:-1}"
}

case "$PHASE" in
    backup|apply) ;;
    *) fail 'Usage: repair_database.sh backup|apply' 2 ;;
esac

[ -n "${POSTGRES_USER:-}" ] || fail 'Database role configuration is missing.' 2
[ -n "${POSTGRES_DB:-}" ] || fail 'Database name configuration is missing.' 2
[ -n "${POSTGRES_PASSWORD:-}" ] || fail 'Database password configuration is missing.' 2

# Interactive password prompts read one line at a time. Never partially apply a
# multiline credential. Password contents are not printed on any error path.
CR=$(printf '\r')
case "$POSTGRES_PASSWORD" in
    *'
'*|*"$CR"*) fail 'Multiline credentials are not supported; no password was changed.' 2 ;;
esac

command -v psql >/dev/null 2>&1 || fail 'PostgreSQL client tools are unavailable.' 2
command -v pg_dump >/dev/null 2>&1 || fail 'PostgreSQL backup tools are unavailable.' 2
command -v pg_restore >/dev/null 2>&1 || fail 'PostgreSQL restore tools are unavailable.' 2
command -v sha256sum >/dev/null 2>&1 || fail 'Checksum verification is unavailable.' 2

[ ! -L "$STATE_DIR" ] || fail 'Unsafe recovery directory; no change was made.' 2
if [ -e "$STATE_DIR" ] && [ ! -d "$STATE_DIR" ]; then
    fail 'Recovery directory is unavailable; no change was made.' 2
fi
mkdir -p "$STATE_DIR" || fail 'Recovery directory cannot be prepared.' 2
chmod 700 "$STATE_DIR" || fail 'Recovery directory permissions cannot be protected.' 2

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    fail 'Another recovery may be running. No change was made.' 3
fi
cleanup() {
    rmdir "$LOCK_DIR" 2>/dev/null || :
}
trap cleanup 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

for FILE in database.dump database.dump.tmp database.dump.sha256 target.json target.current verified; do
    [ ! -L "$STATE_DIR/$FILE" ] || fail 'Unsafe recovery file; no change was made.' 2
done

export PGCONNECT_TIMEOUT=5
export PGPASSFILE=/dev/null
export PSQL_HISTORY=/dev/null

local_psql() {
    # Force the existing local Unix socket; never change authentication rules.
    psql -X -w -q -v ON_ERROR_STOP=1 -h "$SOCKET_DIR" -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
}

write_target() {
    local_psql -At -c "SELECT json_build_object('role', current_user, 'database', current_database(), 'database_oid', (SELECT oid FROM pg_database WHERE datname=current_database()), 'cluster', (SELECT system_identifier::text FROM pg_control_system()))::text" > "$1" 2>/dev/null
}

if [ "$PHASE" = backup ]; then
    # Invalidate any previous approval BEFORE starting a new backup attempt.
    rm -f "$STATE_DIR/verified" "$STATE_DIR/database.dump.tmp" "$STATE_DIR/database.dump.sha256"
    if ! write_target "$STATE_DIR/target.json"; then
        fail 'Local administrative access could not be verified. No password was changed.' 4
    fi
    if ! pg_dump -w -h "$SOCKET_DIR" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$STATE_DIR/database.dump.tmp" >/dev/null 2>&1; then
        rm -f "$STATE_DIR/database.dump.tmp"
        fail 'Database backup failed. Password alignment is forbidden.' 5
    fi
    [ -s "$STATE_DIR/database.dump.tmp" ] || fail 'Database backup is empty. Password alignment is forbidden.' 5
    if ! pg_restore --list "$STATE_DIR/database.dump.tmp" >/dev/null 2>&1; then
        rm -f "$STATE_DIR/database.dump.tmp"
        fail 'Database backup verification failed. Password alignment is forbidden.' 5
    fi
    mv "$STATE_DIR/database.dump.tmp" "$STATE_DIR/database.dump" || fail 'Verified backup cannot be stored.' 5
    if ! (cd "$STATE_DIR" && sha256sum database.dump > database.dump.sha256); then
        fail 'Backup checksum cannot be stored. Password alignment is forbidden.' 5
    fi
    chmod 600 "$STATE_DIR/database.dump" "$STATE_DIR/database.dump.sha256" "$STATE_DIR/target.json"
    printf '%s\n' 'tvm-connection-repair-v1' > "$STATE_DIR/verified"
    printf '%s\n' 'Verified database backup is ready. Copy it to the PC before applying the repair.'
    exit 0
fi

[ -f "$STATE_DIR/verified" ] || fail 'A fresh verified backup is required before password alignment.' 5
[ -s "$STATE_DIR/database.dump" ] || fail 'The database backup is missing or empty. No password was changed.' 5
[ -s "$STATE_DIR/database.dump.sha256" ] || fail 'The backup checksum is missing. No password was changed.' 5
[ -s "$STATE_DIR/target.json" ] || fail 'The backup target is missing. No password was changed.' 5
if ! (cd "$STATE_DIR" && sha256sum -c database.dump.sha256 >/dev/null 2>&1); then
    rm -f "$STATE_DIR/verified"
    fail 'The backup has changed. No password was changed.' 5
fi
if ! pg_restore --list "$STATE_DIR/database.dump" >/dev/null 2>&1; then
    rm -f "$STATE_DIR/verified"
    fail 'The backup cannot be verified. No password was changed.' 5
fi
if ! write_target "$STATE_DIR/target.current"; then
    fail 'Local administrative access could not be verified. No password was changed.' 4
fi
if ! cmp -s "$STATE_DIR/target.json" "$STATE_DIR/target.current"; then
    rm -f "$STATE_DIR/verified"
    fail 'The database target differs from the backup. No password was changed.' 5
fi

# Consume the approval before touching the role. A failure requires another
# verified backup; do not retry against an old approval after an uncertain result.
rm -f "$STATE_DIR/verified"
if ! printf '%s\n%s\n' "$POSTGRES_PASSWORD" "$POSTGRES_PASSWORD" | local_psql -c '\password' >/dev/null 2>&1; then
    fail 'Password alignment could not be confirmed. No data or privileges were modified; verify the connection before retrying.' 6
fi
printf '%s\n' 'Database password aligned with the container configuration. Data and privileges were preserved; verify TCP authentication next.'
