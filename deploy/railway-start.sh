#!/bin/sh
set -eu
: "${DZ_DATABASE_URL:?Set a PostgreSQL connection string}"
: "${DZ_ACCESS_TOKEN:?Set a random access token of at least 32 characters}"
exec python -m dz.platform.cli serve --host 0.0.0.0 --port "${PORT:-8771}"
