#!/usr/bin/env bash
set -euo pipefail

MYSQL_SOCKET="${MYSQL_SOCKET:-/tmp/xcul-mysql.sock}"
MYSQL_PID_FILE="${MYSQL_PID_FILE:-/tmp/xcul-mysql.pid}"

if [[ ! -f "$MYSQL_PID_FILE" ]]; then
    echo "MariaDB pid file not found at $MYSQL_PID_FILE" >&2
    exit 1
fi

pid="$(<"$MYSQL_PID_FILE")"
if [[ -z "$pid" ]]; then
    echo "MariaDB pid file is empty" >&2
    exit 1
fi

if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$MYSQL_PID_FILE" "$MYSQL_SOCKET"
    echo "MariaDB is not running. Removed stale pid/socket files."
    exit 0
fi

kill "$pid"

for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$MYSQL_PID_FILE" "$MYSQL_SOCKET"
        echo "MariaDB stopped"
        exit 0
    fi
    sleep 1
done

echo "MariaDB is still running after waiting for shutdown." >&2
exit 1
