#!/bin/sh
set -e
mkdir -p /app/data /app/static/kapaklar
chown -R kitaptakipappuser:kitaptakipappuser /app/data /app/static/kapaklar
exec gosu kitaptakipappuser "$@"
