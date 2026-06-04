from pathlib import Path
import socket

from .common import *
import pymysql

pymysql.install_as_MySQLdb()


DEBUG = True

SECRET_KEY = config('SECRET_KEY', default='django-insecure-dev-only-change-me')


def _first_live_db_socket(*candidates):
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(0.2)
            client.connect(str(path))
        except OSError:
            continue
        else:
            client.close()
            return str(path)
    return ''


DEFAULT_DB_SOCKET = _first_live_db_socket(
    '/tmp/xcul-mysql.sock',
    '/run/mysqld/mysqld.sock',
)
DB_SOCKET = config('DB_SOCKET', default=DEFAULT_DB_SOCKET)

DATABASE_OPTIONS = {
    'charset': 'utf8mb4',
    'use_unicode': True,
    'init_command': "SET NAMES 'utf8mb4'",
}

if DB_SOCKET:
    DATABASE_OPTIONS['unix_socket'] = DB_SOCKET


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': config('DB_NAME', default='bayezieu_schooldb'),
        'USER': config('DB_USER', default='bayezieu_bayan_user'),
        'PASSWORD': config('DB_PASSWORD', default='@bayan%dbuser'),
        'HOST': config('DB_HOST', default='localhost' if DB_SOCKET else '127.0.0.1'),
        'PORT': config('DB_PORT', default='3307' if DB_SOCKET else '3306'),
        'OPTIONS': DATABASE_OPTIONS,
    }
}


# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'schooldb',
#         'USER': 'schooluser',
#         'PASSWORD': 'root@admin',
#         'HOST': 'localhost',
#         'PORT': '5432',
#     }
# }



# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': str(BASE_DIR / 'db.sqlite3'),
#     }
# }
