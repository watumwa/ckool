#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MYSQL_DATA_DIR="${MYSQL_DATA_DIR:-$ROOT_DIR/tmp/mysql-data}"
MYSQL_SOCKET="${MYSQL_SOCKET:-/tmp/xcul-mysql.sock}"
MYSQL_PID_FILE="${MYSQL_PID_FILE:-/tmp/xcul-mysql.pid}"
MYSQL_ERROR_LOG="${MYSQL_ERROR_LOG:-$ROOT_DIR/tmp/xcul-mysql.err}"
MYSQL_STDOUT_LOG="${MYSQL_STDOUT_LOG:-/tmp/xcul-mysql.stdout}"
MYSQL_USER="${MYSQL_USER:-$(id -un)}"

if [[ ! -d "$MYSQL_DATA_DIR/mysql" ]]; then
    echo "MariaDB data directory not found at $MYSQL_DATA_DIR" >&2
    echo "Copy or import a local data directory before starting MariaDB." >&2
    exit 1
fi

if [[ -f "$MYSQL_PID_FILE" ]]; then
    running_pid="$(<"$MYSQL_PID_FILE")"
    if [[ -n "$running_pid" ]] && kill -0 "$running_pid" 2>/dev/null; then
        echo "MariaDB is already running with PID $running_pid"
        echo "Socket: $MYSQL_SOCKET"
        exit 0
    fi
fi

if [[ -S "$MYSQL_SOCKET" ]]; then
    rm -f "$MYSQL_SOCKET"
fi

rm -f "$MYSQL_PID_FILE"

nohup mariadbd \
    --datadir="$MYSQL_DATA_DIR" \
    --socket="$MYSQL_SOCKET" \
    --skip-networking \
    --pid-file="$MYSQL_PID_FILE" \
    --log-error="$MYSQL_ERROR_LOG" \
    --user="$MYSQL_USER" \
    >"$MYSQL_STDOUT_LOG" 2>&1 &

for _ in $(seq 1 20); do
    if [[ -S "$MYSQL_SOCKET" ]] && mysqladmin --socket="$MYSQL_SOCKET" ping >/dev/null 2>&1; then
        echo "MariaDB started"
        echo "Socket: $MYSQL_SOCKET"
        echo "PID file: $MYSQL_PID_FILE"
        exit 0
    fi
    sleep 1
done

echo "MariaDB did not become ready. Recent log output:" >&2
if [[ -f "$MYSQL_ERROR_LOG" ]]; then
    tail -n 40 "$MYSQL_ERROR_LOG" >&2
fi
exit 1
