#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MYSQL_SOCKET="${MYSQL_SOCKET:-/tmp/xcul-mysql.sock}"
MYSQL_ROOT_USER="${MYSQL_ROOT_USER:-root}"
DB_NAME="${DB_NAME:-bayezieu_schooldb}"
DB_USER="${DB_USER:-bayezieu_bayan_user}"
DB_PASSWORD="${DB_PASSWORD:-@bayan%dbuser}"
SQL_DUMP="${1:-$ROOT_DIR/bayezieu_schooldb.sql}"

if [[ ! -S "$MYSQL_SOCKET" ]]; then
    echo "MariaDB socket not found at $MYSQL_SOCKET" >&2
    exit 1
fi

if [[ ! -f "$SQL_DUMP" ]]; then
    echo "SQL dump not found at $SQL_DUMP" >&2
    exit 1
fi

mysql_base=(mysql "--socket=$MYSQL_SOCKET" "-u$MYSQL_ROOT_USER")

"${mysql_base[@]}" -e "
DROP DATABASE IF EXISTS \`$DB_NAME\`;
CREATE DATABASE \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
CREATE USER IF NOT EXISTS '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$DB_PASSWORD';
ALTER USER '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
ALTER USER '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'127.0.0.1';
FLUSH PRIVILEGES;
"

"${mysql_base[@]}" "$DB_NAME" < "$SQL_DUMP"

echo "Imported $SQL_DUMP into $DB_NAME using $MYSQL_SOCKET"
